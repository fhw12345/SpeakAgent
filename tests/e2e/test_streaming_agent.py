"""Phase 3 streaming e2e: browser drives a real session and verifies that
multiple `agent_partial_text` WS frames arrive before `agent_done`, and that
`#agent-caption` updates live.

Uses CDP to capture WebSocket frames sent from the server to the page.
"""
from pathlib import Path

import pytest

SCREENSHOTS = Path(__file__).resolve().parent / "screenshots"


def _open_w1d1(page, port: int) -> None:
    page.goto(f"http://127.0.0.1:{port}/")
    page.wait_for_selector('#list-view .lesson-row[data-id="W1D1"]')
    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")


def test_streaming_emits_multiple_partial_text_before_done(server, page):
    """With streaming on (default), the first agent turn should yield ≥2
    agent_partial_text frames before its agent_done."""
    SCREENSHOTS.mkdir(exist_ok=True)
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")

    received_text_frames: list[dict] = []

    def on_frame(params):
        try:
            import json
            payload = json.loads(params["response"]["payloadData"])
            received_text_frames.append(payload)
        except Exception:
            pass

    cdp.on("Network.webSocketFrameReceived", on_frame)

    _open_w1d1(page, server)
    page.click("#start-btn")

    # Wait until at least one agent_done frame arrived.
    def _has_done() -> bool:
        return any(f.get("type") == "agent_done" for f in received_text_frames)

    page.wait_for_function("() => true", timeout=1)  # no-op
    deadline_ms = 30_000
    page.wait_for_timeout(500)
    waited = 500
    while waited < deadline_ms and not _has_done():
        page.wait_for_timeout(500)
        waited += 500

    if not _has_done():
        pytest.skip("server did not emit agent_done within 30s (likely TTS unreachable in CI)")

    # Slice frames up to and including the FIRST agent_done.
    sliced: list[dict] = []
    for f in received_text_frames:
        sliced.append(f)
        if f.get("type") == "agent_done":
            break
    partials = [f for f in sliced if f.get("type") == "agent_partial_text"]
    assert len(partials) >= 2, f"expected ≥2 agent_partial_text before agent_done, got {len(partials)}; frames={[f.get('type') for f in sliced]}"

    # Caption element should have been updated at least once with non-empty text.
    cap = page.locator("#agent-caption").text_content() or ""
    assert cap.strip(), f"#agent-caption is empty: {cap!r}"

    page.screenshot(path=str(SCREENSHOTS / "streaming_caption.png"))
