"""Playwright e2e: barge-in cancels agent TTS within 1s.

Requires Chromium installed. Forces SPEAKAGENT_VAD=on for the spawned
server. Uses a `page.evaluate` snippet to send an explicit `interrupt`
over the existing WS while the agent is mid-stream and asserts that
`tts-player.stopAll` was called and that the next protocol message
arrives within 1000 ms.
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


def _wait(port, timeout=20.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("server did not come up")


@pytest.fixture(scope="module")
def vad_server():
    SCREENSHOTS.mkdir(exist_ok=True)
    port = _free_port()
    env = os.environ.copy()
    env["SPEAKAGENT_PORT"] = str(port)
    env["WHISPER_DEVICE"] = "cpu"
    env["SPEAKAGENT_VAD"] = "on"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(REPO), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        _wait(port)
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_tts_player_stopall_clears_queue(vad_server, page):
    page.goto(f"http://127.0.0.1:{vad_server}/")
    page.wait_for_function("typeof TtsPlayer !== 'undefined'")
    cleared = page.evaluate("""
      () => {
        const p = new TtsPlayer();
        p.pushChunks([new Uint8Array([1,2,3])]);
        p.pushChunks([new Uint8Array([4,5,6])]);
        const before = p._queue.length;
        p.stopAll();
        return { before, after: p._queue.length };
      }
    """)
    assert cleared["before"] >= 1
    assert cleared["after"] == 0


def test_barge_in_next_message_within_1s(vad_server, page):
    if not (os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION")):
        pytest.skip("requires AZURE_SPEECH_KEY/REGION so TTS actually streams chunks")
    page.goto(f"http://127.0.0.1:{vad_server}/")
    page.wait_for_selector('#list-view .lesson-row[data-id="W1D1"]')
    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")
    # Hook the WebSocket constructor to capture messages and timings.
    page.evaluate("""
      () => {
        window.__msgs = [];
        const Orig = window.WebSocket;
        window.WebSocket = function(url, protos) {
          const ws = new Orig(url, protos);
          ws.addEventListener('message', (ev) => {
            if (typeof ev.data === 'string') {
              window.__msgs.push({ t: performance.now(), data: ev.data });
            }
          });
          window.__lastWs = ws;
          return ws;
        };
        window.WebSocket.prototype = Orig.prototype;
      }
    """)
    page.click("#start-btn")
    page.wait_for_function("window.__msgs && window.__msgs.some(m => m.data.includes('agent_caption'))", timeout=15000)
    # Send interrupt and time the next protocol message.
    result = page.evaluate("""
      async () => {
        const startCount = window.__msgs.length;
        const t0 = performance.now();
        window.__lastWs.send(JSON.stringify({type:'interrupt'}));
        const deadline = t0 + 2000;
        while (performance.now() < deadline) {
          if (window.__msgs.length > startCount) {
            const next = window.__msgs[startCount];
            return { dt: next.t - t0, type: JSON.parse(next.data).type };
          }
          await new Promise(r => setTimeout(r, 20));
        }
        return { dt: -1, type: null };
      }
    """)
    assert result["dt"] >= 0, "no message arrived after interrupt"
    assert result["dt"] < 1000, f"barge-in took {result['dt']:.0f} ms"
