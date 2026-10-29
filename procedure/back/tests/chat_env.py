"""직원 채팅 시험 바탕(SPEC-007 §13.1) — 계정 · 토큰 · 방 만들기 도우미. 이름 · 문구는 모두 지어낸 가짜."""

import json
from datetime import timedelta

from app.service.auth import _b64
from tests.helpers import T0

# (login, 역할, 이름) — 상대 후보(active + 비밀번호 있음)
PEOPLE = [("c-amy", "admin", "가람"), ("c-ben", "doctor", "나래"), ("c-cat", "nurse", "다솜"),
          ("c-dan", "coordinator", "라온"), ("c-eve", "counselor", "마루"), ("c-fay", "nurse", "바다")]
OFF = ("c-off", "nurse", "사랑")  # 비활성
NOPW = ("c-nopw", "doctor", "아라")  # 비밀번호 없음(로그인 불가)


def token_for(c, account) -> str:
    """AuthService.login 과 같은 꼴의 토큰 — 시험 계정은 bcrypt 없이(비밀번호 칸 = 아무 값)."""
    exp = c.clock.now() + timedelta(hours=12)
    body = _b64(json.dumps({"sub": account.login_id, "role": account.role, "staffId": account.staff_id,
                            "exp": int(exp.timestamp())}).encode())
    return f"{body}.{c.auth._sign(body)}"


def seed_people(c) -> dict:
    """{login: (Account, 헤더)} — 비활성 · 비밀번호 없음 계정도 행만."""
    with c.repo.tx() as tx:
        for login, role, name in [*PEOPLE, OFF, NOPW]:
            aid = tx.put_account(login, T0, role=role, name=name, staff_id=None, active=login != OFF[0], card=False)
            if login != NOPW[0]:
                tx.update_account(aid, T0, password_hash="test-only-not-a-hash")
        acc = {a.login_id: a for a in tx.accounts()}
    out = {}
    for login, *_ in [*PEOPLE, OFF, NOPW]:
        a = acc[login]
        out[login] = (a, {"Authorization": f"Bearer {token_for(c, a)}"})
    return out


class Chat:
    """HTTP 로 부르는 도우미 — 모든 시험은 TestClient(실 router · async def)로 지난다."""

    def __init__(self, client, c, people):
        self.client, self.c, self.p = client, c, people
        self.n = 0

    def id(self, login: str) -> int:
        return self.p[login][0].id

    def h(self, login: str) -> dict:
        return self.p[login][1]

    def tick(self, ms: int = 1):
        self.c.clock.set(self.c.clock.now() + timedelta(milliseconds=ms))

    def direct(self, me: str, other: str):
        return self.client.post("/api/chat/rooms/direct", json={"accountId": self.id(other)}, headers=self.h(me))

    def group(self, me: str, others: list[str], title: str | None = None):
        body = {"accountIds": [self.id(o) for o in others], **({"title": title} if title is not None else {})}
        return self.client.post("/api/chat/rooms", json=body, headers=self.h(me))

    def send(self, me: str, room: int, text: str | None = "안녕하세요", client_id: str | None = None, **kw):
        self.n += 1
        body = {"clientId": client_id or f"client-{self.n:04d}", **({"text": text} if text is not None else {}), **kw}
        return self.client.post(f"/api/chat/rooms/{room}/messages", json=body, headers=self.h(me))

    def rooms(self, me: str) -> dict:
        r = self.client.get("/api/chat/rooms", headers=self.h(me))
        assert r.status_code == 200, r.json()
        return r.json()

    def room(self, me: str, room: int) -> dict | None:
        return next((x for x in self.rooms(me)["items"] if x["id"] == room), None)

    def msgs(self, me: str, room: int, **q):
        return self.client.get(f"/api/chat/rooms/{room}/messages", params=q, headers=self.h(me))

    def read(self, me: str, room: int, message_id: int):
        return self.client.post(f"/api/chat/rooms/{room}/read", json={"messageId": message_id}, headers=self.h(me))
