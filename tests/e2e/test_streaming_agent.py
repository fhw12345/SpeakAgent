"""Phase 3 e2e: streaming agent turn surfaces partial captions live.

Uses the SPEAKAGENT_FAKE_STREAM stub (see server/agent_turn._fake_stream)
so the test is reliable without a real Claude gateway.
"""
import json
from pathlib import Path

SCREENSHOTS = Path(__file__).resolve().parent / "screenshots"


def _open_w1d1(page, port: int) -> None:
    page.goto(f"http://127.0.0.1:{port}/")
    page.wait_for_selector('#list-view .lesson-row[data-id="W1D1"]')
    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")


def test_streaming_partial_captions_arrive(streaming_server, page):
    """At least 2 agent_partial_text frames arrive before the first agent_done,
    and #agent-caption text updates at least twice."""
    received: list[dict] = []

    def on_websocket(ws):
        def on_frame(payload):
            if isinstance(payload, str):
                try:
                    received.append(json.loads(payload))
                except Exception:
                    pass
        ws.on("framereceived", on_frame)

    page.on("websocket", on_websocket)

    _open_w1d1(page, streaming_server)
    page.click("#start-btn")

    # Wait until either we see an agent_done or timeout.
    page.wait_for_function(
        "document.querySelector('#agent-caption') && "
        "document.querySelector('#agent-caption').textContent.length > 0",
        timeout=15000,
    )
    # Give the streamer time to emit a few sentences.
    page.wait_for_timeout(2500)

    partials_before_first_done: list[dict] = []
    for m in received:
        if m.get("type") == "agent_partial_text":
            partials_before_first_done.append(m)
        if m.get("type") == "agent_done":
            break

    assert len(partials_before_first_done) >= 2, (
        f"expected >=2 agent_partial_text before first agent_done, got "
        f"{len(partials_before_first_done)}; all frames: "
        f"{[m.get('type') for m in received][:30]}"
    )
    page.screenshot(path=str(SCREENSHOTS / "streaming_partials.png"))
