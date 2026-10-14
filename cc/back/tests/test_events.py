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
        sid = next(r["scheduleId"] for r in b["resv"] if r["st"] == "booked")
        t = threading.Thread(target=container.board.check_in, args=(sid, [{"kind": "consult"}]))
        t.start()
        msg = await asyncio.wait_for(gen.__anext__(), timeout=5)
        t.join()
        await gen.aclose()
        return v0, msg

    v0, msg = asyncio.run(run())
    assert msg == f"event: state\ndata: {json.dumps({'version': v0 + 1})}\n\n"
    assert container.bus.count == 0
