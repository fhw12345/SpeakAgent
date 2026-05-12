"""E2E: streaming agent turn emits multiple agent_partial_text before agent_done.

Spins up a real uvicorn server with `SPEAKAGENT_STREAMING=on` and a stub
Claude gateway controlled via env vars. Uses Playwright to open the page,
start a session, and capture WS frames from the browser side.

Skips automatically when the local Claude gateway is unreachable, since
the streaming path can't run without it.
"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest

SCREENSHOTS = Path(__file__).resolve().parent / "screenshots"


def _gateway_up(host: str = "127.0.0.1", port: int = 23333, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _open_w1d1(page, port: int) -> None:
    page.goto(f"http://127.0.0.1:{port}/")
    page.wait_for_selector('#list-view .lesson-row[data-id="W1D1"]')
    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")


@pytest.mark.skipif(
    not _gateway_up(), reason="Claude gateway not reachable on localhost:23333"
)
def test_streaming_emits_multiple_partial_text_before_done(server, page):
    SCREENSHOTS.mkdir(exist_ok=True)
    page.add_init_script(
        """
        window.__wsFrames = [];
        const _ws = window.WebSocket;
        window.WebSocket = function (url, protocols) {
            const sock = new _ws(url, protocols);
            sock.addEventListener('message', (ev) => {
                if (typeof ev.data === 'string') {
                    try { window.__wsFrames.push(JSON.parse(ev.data)); } catch (e) {}
                } else {
                    window.__wsFrames.push({ type: '__binary__', size: ev.data.size || 0 });
                }
            });
            return sock;
        };
        window.WebSocket.prototype = _ws.prototype;
        """
    )
    _open_w1d1(page, server)
    page.click("#start-btn")
    page.wait_for_function(
        "() => window.__wsFrames && window.__wsFrames.some(f => f.type === 'agent_done')",
        timeout=30000,
    )
    frames = page.evaluate("() => window.__wsFrames")

    first_done = next(i for i, f in enumerate(frames) if f.get("type") == "agent_done")
    partials_before_done = [
        f for f in frames[:first_done] if f.get("type") == "agent_partial_text"
    ]
    assert len(partials_before_done) >= 2, (
        f"expected ≥2 agent_partial_text before agent_done, got "
        f"{len(partials_before_done)}; frames={frames[:first_done + 1]}"
    )

    caption_text = page.locator("#agent-caption").text_content()
    assert caption_text and len(caption_text) > 0, "caption div should be populated"
    page.screenshot(path=str(SCREENSHOTS / "streaming_partial_captions.png"))
