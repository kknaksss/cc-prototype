"""SSE — 변경 때 version 을 보낸다(§5.2 · D-29)."""

import asyncio
import json
import threading

from app.api.events import event_stream


def test_sse_sends_version_on_change(container):
    async def run():
        gen = event_stream(container, None, heartbeat=5)
        first = await gen.__anext__()
        assert first.startswith("event: state\n")
        v0 = json.loads(first.split("data: ")[1])["version"]
        b = container.board.board()
        cust = next(c for c in b["customers"] if not c["done"] and c["room"] != "lounge")
        doc = next(s for s in b["staff"] if s["role"] == "의사")
        t = threading.Thread(target=container.board.assign, args=(doc["staffId"], cust["room"]))
        t.start()
        msg = await asyncio.wait_for(gen.__anext__(), timeout=5)
        t.join()
        await gen.aclose()
        return v0, msg

    v0, msg = asyncio.run(run())
    assert msg == f"event: state\ndata: {json.dumps({'version': v0 + 1})}\n\n"
    assert container.bus.count == 0
