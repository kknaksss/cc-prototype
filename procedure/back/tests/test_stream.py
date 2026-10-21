"""WP2 — 조작 뒤 SSE `board` 1개(§7.5)."""

import asyncio
import json

from tests.helpers import seed_staff, seed_visit


def test_action_publishes_board(client, auth, ctr):
    seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1)
    hub = ctr.hub

    async def run():
        gen = hub.frames(ping_sec=5)
        first = json.loads((await gen.__anext__()).split("data: ", 1)[1])
        assert first["cards"][0]["anesthesia"]["runningSince"] is None
        ctr.actions.anesthesia_start("tester", v["visit"])
        frame = await asyncio.wait_for(gen.__anext__(), 1)
        nxt = json.loads(frame.split("data: ", 1)[1])
        assert nxt["version"] == first["version"] + 1 and nxt["cards"][0]["anesthesia"]["runningSince"]
        await gen.aclose()

    asyncio.run(run())


def test_rejected_action_does_not_publish(client, auth, ctr):
    seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1)
    before = ctr.hub.version
    assert client.post(f"/api/visits/{v['visit']}/anesthesia/end", headers=auth).status_code == 409
    assert ctr.hub.version == before
    assert client.post(f"/api/visits/{v['visit']}/anesthesia/start", headers=auth).status_code == 200
    assert ctr.hub.version == before + 1
