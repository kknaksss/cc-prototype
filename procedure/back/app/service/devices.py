"""푸시 기기(SPEC-004 §5-1.1 · §5-3 「기기 확인」) — 등록 · 지우기 · deviceId 확인 · 마지막으로 부른 시각."""

from app.domain.clock import Clock
from app.domain.errors import NotFound
from app.domain.models import Account, Device
from app.repository.repo import Repository

DEFAULT_NAME = {"tablet": "iPad", "phone": "iPhone"}


class DeviceNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("이 기기를 찾을 수 없어요", "device_not_found")


class DeviceService:
    def __init__(self, repo: Repository, clock: Clock):
        self.repo = repo
        self.clock = clock

    def register(self, actor: Account, token: str, name: str | None, kind: str | None) -> int:
        """같은 토큰이 다른 계정에 있으면 지금 계정으로 옮긴다 · 처음 오는 기기는 이름 없으면 「iPhone」/「iPad」."""
        now = self.clock.now()
        token = token.lower()
        with self.repo.tx() as tx:
            known = any(d.token == token for d in tx.devices())
            if not known and not name:
                name = DEFAULT_NAME.get(kind or "phone", "iPhone")
            return tx.put_device(actor.id, token, now, name=name.strip() if name else None, kind=kind)

    def unregister(self, actor: Account, token: str) -> None:
        """자기 계정의 토큰만 지운다 — 남의 것 · 없는 것은 그냥 ok."""
        with self.repo.tx() as tx:
            tx.delete_device(token.lower(), actor.id)

    def check(self, actor: Account, device_id: int | None, *, touch: bool = True) -> Device | None:
        """deviceId 가 그 계정 기기인가 — 아니면 404 device_not_found. None 이면 None(기기 행 없는 앱)."""
        if device_id is None:
            return None
        with self.repo.tx() as tx:
            d = tx.device(device_id)
            if d is None or d.account_id != actor.id:
                raise DeviceNotFound()
            if touch:
                tx.touch_device(d.id, self.clock.now())
        return d

    def own(self, actor: Account, device_id: int | None) -> Device | None:
        """SSE 용 — 남의 계정 · 없는 id 는 무시(None)."""
        try:
            return self.check(actor, device_id)
        except DeviceNotFound:
            return None
