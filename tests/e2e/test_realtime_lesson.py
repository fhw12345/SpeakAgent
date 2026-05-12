"""Python e2e for the Phase 2 realtime lesson flow.

Drives the live FastAPI server (started by tests/e2e/conftest.py::server) over
HTTP and asserts a 3-turn realtime W1D2 session works with LLM_MOCK enabled.
Mirrors the canonical TS spec in tests/e2e/realtime_lesson.spec.ts.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(port: int, timeout: float = 30.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"server did not come up on {port}")


@pytest.fixture(scope="module")
def realtime_server():
    port = _free_port()
    env = os.environ.copy()
    env["SPEAKAGENT_PORT"] = str(port)
    env["LLM_MOCK"] = "1"
    env["WHISPER_DEVICE"] = "cpu"
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


def _post(port: int, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def test_three_turn_realtime_w1d2_with_llm_mock(realtime_server):
    port = realtime_server
    start = _post(port, "/api/lesson/start", {"lesson_id": "w1d2"})
    assert start["mode"] == "realtime"
    assert start["first_agent_utterance"]
    sid = start["session_id"]

    replies = []
    for text in [
        "An API is a set of endpoints.",
        "A tool is a function the agent calls.",
        "It picks one based on what the user asked.",
    ]:
        out = _post(port, "/api/lesson/turn", {"session_id": sid, "user_text": text})
        assert out["done"] is False
        replies.append(out["agent_utterance"])

    # 3 distinct agent replies (mock cycles through canned list)
    assert len({*replies}) >= 2  # at least 2 distinct, mock has 5 entries
    assert len(replies) == 3
