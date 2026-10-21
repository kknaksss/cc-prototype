"""ccc 로그인 — 계정 카드를 눌러 바로 로그인(1 · 2차 PoC 와 같음 · 비밀번호 검증 없음 · SPEC-004 §3.2 · §3.3).

토큰 = PROC_SESSION_SECRET 로 서명한 `{sub: login_id, role, staffId, exp}` · 만료 PROC_SESSION_HOURS.
검증 = 서명 · 만료 + account 에 login_id 가 있고 active · 역할 · staffId 가 **DB 의 지금 값**과 같아야(다르면 401 — 다시 로그인).
"""

import base64
import hashlib
import hmac
import json
from datetime import timedelta

from app.config import Settings
from app.domain.clock import Clock, iso
from app.domain.errors import Unauthorized
from app.domain.models import Account
from app.repository.repo import Repository
from app.service.accounts import AccountService


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class AuthService:
    def __init__(self, settings: Settings, clock: Clock, repo: Repository, accounts: AccountService):
        self.settings = settings
        self.clock = clock
        self.repo = repo
        self.account_service = accounts

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self.settings.proc_session_secret.encode(), body.encode(), hashlib.sha256).digest())

    def accounts(self) -> list[dict[str, str]]:
        """로그인 카드 목록(card · active). 서명 키가 env 에 없으면 빈 목록(아무도 못 들어온다)."""
        if not self.settings.proc_session_secret:
            return []
        return self.account_service.cards()

    def login(self, user_id: str) -> tuple[str, str, Account]:
        """(token, expiresAt, 계정). 카드 계정이면 토큰을 준다 — 비밀번호는 보지 않는다."""
        if not any(hmac.compare_digest(user_id, a["id"]) for a in self.accounts()):
            raise Unauthorized("invalid_credentials", "아이디 또는 비밀번호가 맞지 않아요")
        with self.repo.tx() as tx:
            account = tx.account(user_id)
        assert account is not None
        exp = self.clock.now() + timedelta(hours=self.settings.proc_session_hours)
        claims = {"sub": account.login_id, "role": account.role, "staffId": account.staff_id, "exp": int(exp.timestamp())}
        body = _b64(json.dumps(claims).encode())
        return f"{body}.{self._sign(body)}", iso(exp), account

    def verify(self, token: str | None) -> Account:
        """토큰 → 로그인 계정(DB 의 지금 값). 없거나 틀리거나 만료 · 비활성 · 역할이 바뀌었으면 401."""
        bad = Unauthorized("unauthorized", "로그인이 필요해요")
        if not token or "." not in token or not self.settings.proc_session_secret:
            raise bad
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(body)):
            raise bad
        try:
            claims = json.loads(_unb64(body))
        except ValueError:
            raise bad from None
        if not isinstance(claims, dict) or claims.get("exp", 0) <= self.clock.now().timestamp():
            raise bad
        with self.repo.tx() as tx:
            account = tx.account(str(claims.get("sub", "")))
        if account is None or not account.active:
            raise bad
        if claims.get("role") != account.role or claims.get("staffId") != account.staff_id:
            raise bad
        return account
