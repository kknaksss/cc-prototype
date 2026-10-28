"""ccc 로그인 — 아이디 + 비밀번호(OQ-601 닫음 · 정상 로그인). 비밀번호 = bcrypt 해시(account.password_hash).

- 해시 없는 계정(그 밖 원장 등) · 비활성 · 없는 아이디 · 틀린 비밀번호 = 같은 401 「아이디 또는 비밀번호가 맞지 않아요」
- 같은 아이디 5회 실패 → 1분 잠금(429 · 메모리) · 성공하면 실패 수를 지운다

토큰 = PROC_SESSION_SECRET 로 서명한 `{sub: login_id, role, staffId, exp}` · 만료 PROC_SESSION_HOURS.
검증 = 서명 · 만료 + account 에 login_id 가 있고 active · 역할 · staffId 가 **DB 의 지금 값**과 같아야(다르면 401 — 다시 로그인).
"""

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta

import bcrypt

from app.config import Settings
from app.domain.clock import Clock, iso
from app.domain.errors import DomainError, Unauthorized
from app.domain.models import Account
from app.repository.repo import Repository
from app.service.accounts import AccountService


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


MAX_FAILS = 5
LOCK_SEC = 60.0
# 없는 아이디도 같은 시간이 걸리게 — 그 자리에서 비교할 가짜 해시
_DUMMY_HASH = bcrypt.hashpw(b"not-a-password", bcrypt.gensalt(rounds=4))


class TooManyAttempts(DomainError):
    status = 429


class AuthService:
    def __init__(self, settings: Settings, clock: Clock, repo: Repository, accounts: AccountService):
        self.settings = settings
        self.clock = clock
        self.repo = repo
        self.account_service = accounts
        self._fails: dict[str, tuple[int, float]] = {}  # login_id → (연속 실패 수, 잠금 풀리는 monotonic 시각)
        # 문진 잠금 나가기(SPEC-004 §3.3 r2 · D7-71) — (계정 id, deviceId | None) 마다 · 로그인 실패 수와 따로
        self._unlock_fails: dict[tuple[int, int | None], tuple[int, float]] = {}
        self.now_mono = time.monotonic  # 시험이 바꾼다

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self.settings.proc_session_secret.encode(), body.encode(), hashlib.sha256).digest())

    def login(self, user_id: str, password: str) -> tuple[str, str, Account]:
        """(token, expiresAt, 계정). 실패는 이유와 상관없이 같은 401 · 5회 실패면 1분 429."""
        bad = Unauthorized("invalid_credentials", "아이디 또는 비밀번호가 맞지 않아요")
        fails, until = self._fails.get(user_id, (0, 0.0))
        if until > self.now_mono():
            raise TooManyAttempts("too_many_attempts", "로그인 실패가 많아요. 1분 뒤 다시 시도해 주세요")
        if until:  # 잠금이 풀렸으면 다시 0 부터
            fails = 0
        with self.repo.tx() as tx:
            account = tx.account(user_id) if user_id else None
        usable = bool(account and account.active and account.password_hash and self.settings.proc_session_secret)
        stored = account.password_hash.encode() if usable and account and account.password_hash else _DUMMY_HASH
        try:
            ok = bcrypt.checkpw(password.encode(), stored) and usable  # 상수 시간 비교 · 없는 아이디도 해시 비교 1번
        except ValueError:  # bcrypt 는 72바이트 넘는 비밀번호를 거절한다 — 그냥 틀린 비밀번호로
            ok = False
        if not ok or account is None:
            fails += 1
            self._fails[user_id] = (fails, self.now_mono() + LOCK_SEC if fails >= MAX_FAILS else 0.0)
            raise bad
        self._fails.pop(user_id, None)
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

    def unlock(self, account: Account, password: str, device_id: int | None) -> None:
        """지금 로그인 계정 비밀번호 확인만(새 토큰 없음). 그 기기만 5회 → 1분 429 · 로그인 · 다른 기기는 안 잠금."""
        key = (account.id, device_id)
        fails, until = self._unlock_fails.get(key, (0, 0.0))
        if until > self.now_mono():
            raise TooManyAttempts("too_many_attempts", "여러 번 틀렸어요. 1분 뒤 다시 시도해 주세요")
        if until:
            fails = 0
        with self.repo.tx() as tx:
            fresh = tx.account(account.login_id)
        stored = fresh.password_hash.encode() if fresh and fresh.password_hash else _DUMMY_HASH
        try:
            ok = bcrypt.checkpw(password.encode(), stored) and bool(fresh and fresh.password_hash)  # 상수 시간 비교
        except ValueError:
            ok = False
        if not ok:
            fails += 1
            self._unlock_fails[key] = (fails, self.now_mono() + LOCK_SEC if fails >= MAX_FAILS else 0.0)
            raise Unauthorized("invalid_credentials", "아이디 또는 비밀번호가 맞지 않아요")
        self._unlock_fails.pop(key, None)
