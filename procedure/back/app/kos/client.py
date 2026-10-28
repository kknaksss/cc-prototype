"""KOS 클라이언트 — 공개(open) · 내부(internal) 두 가지 · 토큰은 kos_token 에 보관(SPEC-003 §4.1 · D-07).

- 공개: `exchange-token {key}` → `{token}` · `Authorization: <token>`(Bearer 없음) · 만료 시각 없음 → 401 로만 갱신
- 내부: `sign-in {email,password}` → `{data{id,…,token}, tokenExpiredDateTimeUtc}` · `Authorization: Bearer <token>`
  · 만료 10분 전이면 새로 받는다
- 시스템 계정 id(담당자 지정 · 원장 목록 제외) = sign-in 직후 내부 `get-user-account` 의 `data.id`(테넌트 계정 id ·
  getAccounts 의 id 와 같다). `sign-in` 의 `data.id` 는 사용자 id 라 담당자로 넣으면 KOS 가 200 을 주고 무시한다
  (2026-10-21 데모 실호출 확인)
- 401 이면 다시 받기 1회 후 같은 요청 1회
- 키 · 비밀번호 · 토큰은 로그 · 오류 메시지에 싣지 않는다(KosError 는 HTTP 상태 · 오류 이름만)
"""

import logging
from datetime import timedelta
from typing import Any

import httpx

from app.config import Settings
from app.domain.clock import Clock, parse
from app.repository.repo import Repository

log = logging.getLogger("procedure.kos")

OPEN_TOKEN_PATH = "open/authorization/commands/exchange-token"
SIGN_IN_PATH = "common/v1/user/commands/sign-in"
USER_ACCOUNT_PATH = "v1/account/queries/get-user-account"
REFRESH_BEFORE = timedelta(minutes=10)


class KosError(Exception):
    """KOS 호출 실패 — message 에 비밀값 · 응답 본문을 넣지 않는다."""

    def __init__(self, message: str, status: int | None = None, name: str = "",
                 error_properties: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.status = status
        self.name = name  # KOS 오류 이름(className 끝) — 없으면 빈 문자열
        # 거절 이유(SPEC-005 §4.4) — [{key, reason}] 만 · 값은 싣지 않는다
        self.error_properties = error_properties or []

    def has(self, key: str, reason: str) -> bool:
        return any(p.get("key") == key and p.get("reason") == reason for p in self.error_properties)


def _error_of(resp: httpx.Response) -> KosError:
    name = ""
    props: list[dict[str, str]] = []
    try:
        body = resp.json()
        if isinstance(body, dict):
            name = str(body.get("className") or body.get("code") or "").rsplit(".", 1)[-1][:60]
            for p in body.get("errorProperties") or []:
                if isinstance(p, dict) and (p.get("key") or p.get("reason")):
                    props.append({"key": str(p.get("key") or "")[:80], "reason": str(p.get("reason") or "")[:60]})
    except ValueError:
        pass
    return KosError(f"HTTP {resp.status_code}" + (f" {name}" if name else ""), resp.status_code, name, props)


class KosClient:
    def __init__(self, settings: Settings, repo: Repository, clock: Clock, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self.repo = repo
        self.clock = clock
        self.http = httpx.AsyncClient(timeout=15, transport=transport, follow_redirects=False)

    async def aclose(self) -> None:
        await self.http.aclose()

    # ------------------------------------------------------------------ 토큰
    def system_kos_id(self) -> str | None:
        with self.repo.tx() as tx:
            t = tx.token("internal")
        return t[2] if t else None

    async def _post_raw(self, url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
        try:
            return await self.http.post(url, json=body, headers=headers or {})
        except httpx.HTTPError as e:
            raise KosError(f"network {type(e).__name__}") from None

    async def open_token(self, force: bool = False) -> str:
        with self.repo.tx() as tx:
            saved = tx.token("open")
        if saved and not force:
            return saved[0]
        resp = await self._post_raw(f"{self.s.kos_open_api_base.rstrip('/')}/{OPEN_TOKEN_PATH}", {"key": self.s.kos_open_api_key})
        if resp.status_code // 100 != 2:
            raise _error_of(resp)
        try:
            token = (resp.json() or {}).get("token")
        except (ValueError, AttributeError):
            token = None
        if not token:
            raise KosError("exchange-token: token 없음")
        with self.repo.tx() as tx:
            tx.save_token("open", token, None, None)
        log.info("KOS 공개 토큰 받음")
        return token

    async def internal_token(self, force: bool = False) -> str:
        with self.repo.tx() as tx:
            saved = tx.token("internal")
        now = self.clock.now()
        if saved and not force and saved[1] and saved[1] - REFRESH_BEFORE > now:
            return saved[0]
        resp = await self._post_raw(f"{self.s.kos_internal_api_base.rstrip('/')}/{SIGN_IN_PATH}",
                                    {"email": self.s.kos_system_email, "password": self.s.kos_system_password})
        if resp.status_code // 100 != 2:
            raise _error_of(resp)
        try:
            body = resp.json() or {}
            data = body.get("data") or {}
        except (ValueError, AttributeError):
            raise KosError("sign-in: 응답 형식") from None
        token = data.get("token")
        if not token:
            raise KosError("sign-in: token 없음")
        expires = parse(body.get("tokenExpiredDateTimeUtc")) or now + timedelta(hours=12)
        account_id = await self._user_account_id(token)
        with self.repo.tx() as tx:
            tx.save_token("internal", token, expires, account_id)
            tx.set_doctor_flags(account_id, self.s.exclude_account_ids)  # 시스템 계정은 원장 목록에서 뺀다
        log.info("KOS 내부 토큰 받음(만료 %s)", expires.isoformat())
        return token

    async def _user_account_id(self, token: str) -> str:
        url = f"{self.s.kos_internal_api_base.rstrip('/')}/tenants/{self.s.kos_tenant_id}/{USER_ACCOUNT_PATH}"
        resp = await self._post_raw(url, {}, {"Authorization": f"Bearer {token}"})
        if resp.status_code // 100 != 2:
            raise _error_of(resp)
        try:
            account_id = ((resp.json() or {}).get("data") or {}).get("id")
        except (ValueError, AttributeError):
            account_id = None
        if not account_id:
            raise KosError("get-user-account: id 없음")
        return str(account_id)

    # ------------------------------------------------------------------ 호출
    async def _call(self, url: str, body: dict[str, Any], kind: str) -> dict[str, Any]:
        for attempt in (0, 1):
            if kind == "open":
                headers = {"Authorization": await self.open_token(force=attempt == 1)}
            else:
                headers = {"Authorization": f"Bearer {await self.internal_token(force=attempt == 1)}"}
            resp = await self._post_raw(url, body, headers)
            if resp.status_code == 401 and attempt == 0:
                log.info("KOS %s 401 — 토큰 다시 받기", kind)
                continue
            if resp.status_code // 100 != 2:
                raise _error_of(resp)
            if not resp.content:
                return {}
            try:
                out = resp.json()
            except ValueError:
                return {}
            return out if isinstance(out, dict) else {"data": out}
        raise KosError("HTTP 401", 401)  # pragma: no cover — 위 루프가 두 번째에 raise 한다

    async def open(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._call(f"{self.s.kos_open_api_base.rstrip('/')}/{path}", body, "open")

    async def internal(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """`{KOS_INTERNAL_API_BASE}/tenants/{tenantId}/<path>`."""
        url = f"{self.s.kos_internal_api_base.rstrip('/')}/tenants/{self.s.kos_tenant_id}/{path}"
        return await self._call(url, body, "internal")

    async def put_presigned(self, url: str, data: bytes, content_type: str) -> None:
        """공개 `generate-uploading-url` 이 준 presigned URL 로 PUT(SPEC-004 §6.16 ④-c) — 인증 헤더 없음.

        URL(서명 값)은 로그 · 오류에 싣지 않는다(httpx 로그는 WARNING 이상만 · main).
        """
        try:
            resp = await self.http.put(url, content=data, headers={"Content-Type": content_type})
        except httpx.HTTPError as e:
            raise KosError(f"network {type(e).__name__}") from None
        if resp.status_code // 100 != 2:
            raise KosError(f"HTTP {resp.status_code} presigned-put", resp.status_code)

    async def send(self, api: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await (self.open(path, body) if api == "open" else self.internal(path, body))
