"""APNs 직접 발송(SPEC-004 §5-1.2) — HTTP/2 · ES256 JWT(40분마다 새로).

키 · 팀 id · JWT · 기기 토큰 전체는 로그 · 오류에 싣지 않는다.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import jwt

from app.config import Settings

HOSTS = {"production": "https://api.push.apple.com", "sandbox": "https://api.sandbox.push.apple.com"}
JWT_TTL_SEC = 40 * 60


@dataclass(frozen=True)
class ApnsResult:
    status: int | None  # None = 네트워크 오류
    reason: str | None
    apns_id: str | None = None  # 응답 헤더 apns-id


class ApnsClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self.http = httpx.AsyncClient(http2=transport is None, transport=transport, timeout=10)
        self._jwt: tuple[str, float] | None = None

    async def aclose(self) -> None:
        await self.http.aclose()

    def sign(self) -> str:
        return self._token()

    def _token(self) -> str:
        now = time.time()
        if self._jwt is None or now - self._jwt[1] >= JWT_TTL_SEC:
            key = Path(self.s.apns_key_path).read_text()
            token = jwt.encode({"iss": self.s.apns_team_id, "iat": int(now)}, key, algorithm="ES256",
                               headers={"kid": self.s.apns_key_id})
            self._jwt = (token, now)
        return self._jwt[0]

    async def send(self, device_token: str, payload: dict[str, Any], expiration: int = 0) -> ApnsResult:
        """expiration = apns-expiration(유닉스 초) — 0 = 바로 못 주면 버림(호출 · 띄우기). 채팅만 보낼 때 + 1일(SPEC-007 §8)."""
        url = f"{HOSTS[self.s.apns_env]}/3/device/{device_token}"
        headers = {"authorization": f"bearer {self._token()}", "apns-topic": self.s.apns_bundle_id,
                   "apns-push-type": "alert", "apns-priority": "10", "apns-expiration": str(expiration)}
        try:
            resp = await self.http.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            return ApnsResult(None, type(e).__name__)
        reason = None
        if resp.status_code != 200:
            try:
                reason = (resp.json() or {}).get("reason")
            except ValueError:
                reason = None
        return ApnsResult(resp.status_code, reason, resp.headers.get("apns-id"))
