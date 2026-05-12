"""Playwright E2E for realtime W1D2 lesson — PRD AC #8.

Drives 3 mocked user turns end-to-end via the browser UI:
  1. fetch /api/lessons (already wired by list_view.js)
  2. click W1D2 → app.js calls POST /api/lesson/start
  3. server returns mode=realtime, first_agent_utterance (LLM_MOCK=1 canned)
  4. type 3 user replies, each calling POST /api/lesson/turn
  5. assert transcript pane has 1 initial agent + 3 reply agent turns + 3 user turns
  6. assert lesson is not done before turn 6

Note: the PRD asked for a TypeScript spec (`realtime_lesson.spec.ts`); the repo's
e2e harness is pytest-playwright (Python), so we ship the equivalent test here to
match existing convention. The acceptance behavior is identical.
"""
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
def realtime_server():
    """Spawn uvicorn with LLM_MOCK=1 (and STT/TTS mocks reserved for future)."""
    SCREENSHOTS.mkdir(exist_ok=True)
    port = _free_port()
    env = os.environ.copy()
    env["SPEAKAGENT_PORT"] = str(port)
    env["WHISPER_DEVICE"] = "cpu"
    env["LLM_MOCK"] = "1"
    env["STT_MOCK"] = "1"
    env["TTS_MOCK"] = "1"
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


def test_realtime_w1d2_three_turn_flow(realtime_server, page):
    page.goto(f"http://127.0.0.1:{realtime_server}/")
    page.wait_for_selector("#list-view .lesson-row")

    page.click('.lesson-row[data-id="W1D2"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")

    page.wait_for_selector("#realtime-controls:not([hidden])", timeout=5000)
    page.wait_for_selector("#dialogue .agent")

    initial_agent = page.locator("#dialogue .agent").nth(0).text_content()
    assert "tools and APIs" in initial_agent, f"expected canned opener, got: {initial_agent}"

    for i, reply in enumerate(["A tool helps the model.", "An API is an interface.", "It picks the right one."]):
        page.fill("#realtime-input", reply)
        page.click("#realtime-send")
        page.wait_for_function(
            "n => document.querySelectorAll('#dialogue .agent').length >= n",
            arg=i + 2,
        )

    agent_turns = page.locator("#dialogue .agent")
    user_turns = page.locator("#dialogue .user")
    assert agent_turns.count() == 4, f"expected 1 initial + 3 reply agent turns, got {agent_turns.count()}"
    assert user_turns.count() == 3, f"expected 3 user turns, got {user_turns.count()}"

    texts = [agent_turns.nth(i).text_content() for i in range(4)]
    assert len(set(texts)) == 4, f"expected 4 distinct agent utterances, got: {texts}"

    status = page.text_content("#status") or ""
    assert "complete" not in status.lower(), f"lesson should not be done before turn 6, status={status!r}"

    page.screenshot(path=str(SCREENSHOTS / "realtime_lesson.png"))
