"""Shared fixtures for browser e2e tests."""
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
    yield from _start_server({})


@pytest.fixture(scope="module")
def mock_llm_server():
    """Like `server`, but the subprocess has LLM_MOCK=1/STT_MOCK=1/TTS_MOCK=1.
    Used by realtime e2e tests that must be deterministic."""
    yield from _start_server({"LLM_MOCK": "1", "STT_MOCK": "1", "TTS_MOCK": "1"})


def _start_server(extra_env: dict):
    SCREENSHOTS.mkdir(exist_ok=True)
    port = _free_port()
    env = os.environ.copy()
    env["SPEAKAGENT_PORT"] = str(port)
    env["WHISPER_DEVICE"] = "cpu"
    env.update(extra_env)
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
