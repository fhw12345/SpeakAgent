"""Real browser E2E tests using Playwright.

These tests start a real uvicorn server and drive a real Chromium browser
against it. They need the AZURE_SPEECH_KEY+REGION env vars to actually
hear voice (otherwise TTS falls back to edge-tts which may 403). For
checking message protocol / UI rendering, the env vars are not required.

Run separately from the rest:
    pytest tests/e2e/ -v
or:
    pytest -v --no-header  (will skip e2e if chromium not installed)
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
def server():
    """Start a real uvicorn server in a subprocess. Yields port. Tears down."""
    SCREENSHOTS.mkdir(exist_ok=True)
    port = _free_port()
    env = os.environ.copy()
    env["SPEAKAGENT_PORT"] = str(port)
    env["WHISPER_DEVICE"] = "cpu"
    # We don't import the AZURE keys here on purpose — e2e tests should be
    # robust to fallback paths. Real keys can be exported by the user before
    # invocation if they want true Azure TTS.
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


def test_homepage_renders(server, page):
    """Smoke: page loads, lesson title appears in <header>."""
    page.goto(f"http://127.0.0.1:{server}/")
    page.wait_for_selector("#lesson-title")
    title = page.text_content("#lesson-title")
    assert title and "Loading" not in title, f"title still loading: {title!r}"
    assert "Week 1" in title or "AI Agent" in title or "w1d1" in title.lower(), \
        f"unexpected title: {title!r}"
    page.screenshot(path=str(SCREENSHOTS / "homepage.png"))


def test_dialogue_pane_exists(server, page):
    """The dialogue, controls, scorecard, dev-panel sections all render."""
    page.goto(f"http://127.0.0.1:{server}/")
    for sel in ["#dialogue", "#start-btn", "#ptt-btn", "#status",
                "#scorecard", "#dev-panel"]:
        assert page.locator(sel).count() == 1, f"missing element {sel}"


def test_session_starts_and_first_caption_appears(server, page):
    """Click Start lesson, wait for first agent caption div to appear in dialogue."""
    page.goto(f"http://127.0.0.1:{server}/")
    page.click("#start-btn")
    # First caption should arrive within ~5s (Azure TTS HTTP round-trip).
    page.wait_for_selector("#dialogue .agent", timeout=15000)
    captions = page.locator("#dialogue .agent").all_text_contents()
    assert len(captions) >= 1, "no agent caption appeared"
    assert "Coach:" in captions[0], f"unexpected caption: {captions[0]!r}"
    page.screenshot(path=str(SCREENSHOTS / "first_caption.png"))


def test_translation_and_gloss_render_for_first_glossed_turn(server, page):
    """W1D1 turn 3 has gloss; verify .translation + .gloss elements render."""
    page.goto(f"http://127.0.0.1:{server}/")
    page.click("#start-btn")
    # Wait long enough for a few agent turns to come through.
    page.wait_for_selector("#dialogue .gloss", timeout=30000)
    gloss_texts = page.locator("#dialogue .gloss").all_text_contents()
    translations = page.locator("#dialogue .translation").all_text_contents()
    assert len(gloss_texts) >= 1, "no gloss element rendered"
    assert len(translations) >= 1, "no translation element rendered"
    # Sanity: gloss should contain IPA marker or Chinese
    sample = gloss_texts[0]
    assert "/" in sample or any("一" <= c <= "鿿" for c in sample), \
        f"gloss looks empty: {sample!r}"
    page.screenshot(path=str(SCREENSHOTS / "gloss_visible.png"))
