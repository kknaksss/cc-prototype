"""계정 만들기(SPEC-004 §3.1) — admin · nurse · coordinator(SPEC-005 §3.4) 는 env 로 1행,
doctor 는 원장 목록(SPEC-003 §4.6) 한 명당 1행 · counselor 는 상담사 목록(SPEC-005 §5.8) 한 명당 1행(§3.7).

- env 값이 비면 그 계정 · 카드를 만들지 않는다(이미 있던 행은 비활성 — 아무도 못 들어오는 쪽이 기본)
- 의사 카드 = `CCC_DOCTOR_KOS_ACCOUNT_ID` 원장 1명(login_id = `CCC_DOCTOR_ID`). 나머지 원장 = 내부 login_id · 카드 없음
- 상담사 카드 = `CCC_COUNSELOR_KOS_ACCOUNT_ID` 상담사 1명(login_id = `CCC_COUNSELOR_ID`) — 의사와 같은 규칙
- 목록에서 빠진 원장 · 상담사의 계정은 active=false(행은 남김)
"""

import logging

import bcrypt

from app.config import Settings
from app.domain.clock import Clock
from app.domain.models import Staff
from app.repository.repo import Repository, Tx
from app.service.reservations import _counselors

log = logging.getLogger("procedure")


def internal_doctor_login(staff_id: int) -> str:
    return f"doctor-{staff_id}"


def internal_counselor_login(staff_id: int) -> str:
    return f"counselor-{staff_id}"


class AccountService:
    def __init__(self, repo: Repository, settings: Settings, clock: Clock):
        self.repo = repo
        self.s = settings
        self.clock = clock

    def sync(self) -> None:
        with self.repo.tx() as tx:
            self._fixed(tx, "admin", self.s.ccc_admin_id, "관리자")
            self._fixed(tx, "nurse", self.s.ccc_nurse_id, self.s.ccc_nurse_name or "간호사")
            self._fixed(tx, "coordinator", self.s.ccc_coord_id, self.s.ccc_coord_name or "코디")  # SPEC-005 §3.4
            self._doctors(tx)
            self._counselors(tx)
            self._passwords(tx)

    def _passwords(self, tx: Tx) -> None:
        """비밀번호 원천 = env(OQ-601) → bcrypt 해시로 account 에.

        어드민 · PoC 의사 · 간호사만 · 그 밖 계정은 해시 없음(로그인 불가).

        env 값이 지금 해시와 맞으면 다시 만들지 않는다(서버 시작 · 1시간마다 sync 해도 해시가 그대로).
        """
        now = self.clock.now()
        source = {"admin": (self.s.ccc_admin_id, self.s.ccc_admin_password),
                  "nurse": (self.s.ccc_nurse_id, self.s.ccc_nurse_password),
                  "coordinator": (self.s.ccc_coord_id, self.s.ccc_coord_password),
                  "doctor": (self.s.ccc_doctor_id, self.s.ccc_doctor_password),
                  "counselor": (self.s.ccc_counselor_id, self.s.ccc_counselor_password)}
        for a in tx.accounts():
            login_id, password = source.get(a.role, ("", ""))
            want = password if (a.login_id == login_id and login_id and a.active and a.card) else ""
            if not want:
                if a.password_hash is not None:
                    tx.update_account(a.id, now, password_hash=None)
                continue
            if a.password_hash and bcrypt.checkpw(want.encode(), a.password_hash.encode()):
                continue
            hashed = bcrypt.hashpw(want.encode(), bcrypt.gensalt(rounds=self.s.proc_bcrypt_rounds)).decode()
            tx.update_account(a.id, now, password_hash=hashed)

    def _fixed(self, tx: Tx, role: str, login_id: str, name: str) -> None:
        now = self.clock.now()
        for a in tx.accounts():  # 같은 역할의 다른(옛) 고정 계정은 비활성
            if a.role == role and a.login_id != login_id and (a.active or a.card):
                tx.update_account(a.id, now, active=False, card=False)
        if login_id:
            tx.put_account(login_id, now, role=role, name=name, staff_id=None, active=True, card=True)

    def _doctors(self, tx: Tx) -> None:
        staff = tx.staff_by_kos()
        listed = {s.id: s for s in staff.values() if s.is_doctor}
        self._linked(tx, "doctor", listed, staff, self.s.ccc_doctor_kos_account_id, self.s.ccc_doctor_id,
                     internal_doctor_login, "의사 카드를 만들지 않음 — CCC_DOCTOR_KOS_ACCOUNT_ID 원장이 원장 목록에 없음"
                     "(비활성 · 시스템 · 제외 · 미조회)")

    def _counselors(self, tx: Tx) -> None:
        """§3.7 — 상담사 목록 = 예약 현황 [실장 호출] 목록과 같은 함수(새 기준 금지)."""
        staff = tx.staff_by_kos()
        system = tx.token("internal")
        listed = {s.id: s for s in _counselors(staff.values(), system[2] if system else None, self.s.exclude_account_ids)}
        self._linked(tx, "counselor", listed, staff, self.s.ccc_counselor_kos_account_id, self.s.ccc_counselor_id,
                     internal_counselor_login,
                     "상담사 카드를 만들지 않음 — CCC_COUNSELOR_KOS_ACCOUNT_ID 상담사가 상담사 목록에 없음"
                     "(비활성 · 시스템 · 제외 · 미조회)")

    def _linked(self, tx: Tx, role: str, listed: dict[int, Staff], staff: dict[str, Staff], card_kos_id: str,
                card_login: str, internal, why_no_card: str) -> None:
        """KOS 직원 한 명당 계정 1행(의사 · 상담사) — 카드 1명만 env 아이디 · 나머지 내부 login_id · 빠지면 비활성."""
        now = self.clock.now()
        card_staff = staff.get(card_kos_id) if card_kos_id else None
        if card_kos_id and card_login and (card_staff is None or card_staff.id not in listed):
            log.warning(why_no_card)
        card_id = card_staff.id if card_staff is not None and card_staff.id in listed and card_login else None
        existing = {a.staff_id: a for a in tx.accounts() if a.role == role and a.staff_id is not None}
        for a in existing.values():  # 목록에서 빠짐 → 비활성(행은 남김)
            if a.staff_id not in listed and (a.active or a.card):
                tx.update_account(a.id, now, active=False, card=False)
        for sid, s in listed.items():
            is_card = sid == card_id
            login_id = card_login if is_card else internal(sid)
            holder = tx.account(login_id)
            if holder is not None and (holder.staff_id != sid or holder.role != role):  # 다른 행이 그 login_id 를 들면 비킨다
                tx.update_account(holder.id, now, login_id=f"retired-{holder.id}", active=False, card=False)
            prev = existing.get(sid)
            if prev is not None and prev.login_id != login_id:
                tx.update_account(prev.id, now, login_id=login_id)
            tx.put_account(login_id, now, role=role, name=s.name, staff_id=sid, active=True, card=is_card)
