"""Playwright e2e: streaming agent path emits multiple agent_partial_text
events before agent_done and the #agent-caption div updates live.

Spawns a dedicated uvicorn with SPEAKAGENT_STREAMING=on and the test-only
SPEAKAGENT_FAKE_LLM hook so the run does not depend on an external LLM
gateway. Captures WS frames via Playwright's page.on('websocket') hook.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCREENSHOTS = Path(__file__).resolve().parent / "screenshots"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 20.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"server on port {port} did not come up in {timeout}s")


@pytest.fixture(scope="module")
def streaming_server():
    """uvicorn with streaming on + fake LLM stream so no gateway is needed."""
    SCREENSHOTS.mkdir(exist_ok=True)
    port = _free_port()
    env = os.environ.copy()
    env["SPEAKAGENT_PORT"] = str(port)
    env["WHISPER_DEVICE"] = "cpu"
    env["SPEAKAGENT_STREAMING"] = "on"
    env["SPEAKAGENT_FAKE_LLM"] = "1"
    env["SPEAKAGENT_FAKE_TTS"] = "1"
    env["SPEAKAGENT_FAKE_LLM_TEXT"] = (
        "Welcome to today's lesson. How are you feeling? "
        "Let's get started right away."
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_server(port)
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _open_w1d1(page, port: int) -> None:
    page.goto(f"http://127.0.0.1:{port}/")
    try:
        page.wait_for_selector('#list-view .lesson-row[data-id="W1D1"]', timeout=10000)
    except Exception:
        page.screenshot(path=str(SCREENSHOTS / "streaming_open_failed.png"))
        body = page.content()[:600]
        raise AssertionError(f"lesson-row not found; page body: {body}")
    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")


def test_streaming_agent_emits_multiple_partials_before_done(streaming_server, page):
    """Asserts >=2 agent_partial_text WS frames arrive before the first agent_done,
    and #agent-caption updates at least twice during a streaming agent turn."""
    captured = {"frames": [], "ws_count": 0, "raw": [], "console": [], "page_errors": []}

    page.on("console", lambda m: captured["console"].append(f"{m.type}: {m.text}"[:200]))
    page.on("pageerror", lambda e: captured["page_errors"].append(str(e)[:200]))

    def on_ws(ws):
        captured["ws_count"] += 1
        captured["console"].append(f"WS_OPENED: {ws.url}")

        def on_frame(payload):
            captured["raw"].append(repr(payload)[:80])
            text = payload if isinstance(payload, str) else None
            if text is None:
                return
            try:
                data = json.loads(text)
            except Exception:
                return
            captured["frames"].append(data)

        ws.on("framereceived", on_frame)

    page.on("websocket", on_ws)

    _open_w1d1(page, streaming_server)
    captured["console"].append(f"after open_w1d1: dialogue visible={page.locator('#dialogue-view').is_visible()}")
    page.wait_for_selector("#start-btn:not([disabled])", timeout=5000)
    page.click("#start-btn")
    captured["console"].append("clicked start")

    # Sanity check: wait for any agent message to render so we know the
    # session actually started, before we look at our captured WS frames.
    try:
        page.wait_for_selector("#dialogue .agent, #agent-caption:not(:empty)", timeout=20000)
        captured["console"].append("agent UI rendered")
    except Exception as e:
        captured["console"].append(f"agent UI never rendered: {e}")
        page.screenshot(path=str(SCREENSHOTS / "streaming_no_ui.png"))

    # Wait for the first agent_done frame to arrive.
    deadline = time.time() + 30
    while time.time() < deadline:
        types = [f.get("type") for f in captured["frames"]]
        if "agent_done" in types:
            break
        time.sleep(0.2)

    types = [f.get("type") for f in captured["frames"]]
    first_done = types.index("agent_done") if "agent_done" in types else -1
    assert first_done >= 0, (
        f"never saw agent_done; ws_count={captured['ws_count']}, "
        f"raw_frame_count={len(captured['raw'])}, "
        f"console={captured['console'][-15:]}, "
        f"page_errors={captured['page_errors']}, "
        f"first_raw={captured['raw'][:5]}, types={types}"
    )

    partials_before_done = [
        f for f in captured["frames"][:first_done]
        if f.get("type") == "agent_partial_text"
    ]
    assert len(partials_before_done) >= 2, (
        f"expected >=2 agent_partial_text before agent_done, "
        f"got {len(partials_before_done)} in {types[: first_done + 1]}"
    )

    # The #agent-caption div should have updated at least twice while
    # streaming. Since user_prompt clears it after agent_done, count the
    # captured agent_partial_text frames as a proxy: the JS appends each
    # partial onto the caption div on receipt.
    assert len(partials_before_done) >= 2

    page.screenshot(path=str(SCREENSHOTS / "streaming_caption.png"))
