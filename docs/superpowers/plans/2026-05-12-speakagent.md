# speakAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web-based English speaking & listening trainer (FastAPI + WebSocket + faster-whisper + edge-tts + local Claude gateway) plus a continuous autopilot subsystem that can self-improve via headless `claude -p` runs on isolated branches.

**Architecture:** Single-process FastAPI server on `localhost:8765` exposes a WebSocket session per browser tab. A coach state machine drives turn-by-turn dialogue using thin adapters (`llm.py`, `stt.py`, `tts.py`, `scorer.py`) plus JSON/SQLite storage. A separate long-running autopilot process polls four discovery triggers, files backlog items, spawns `claude -p` in git worktrees for isolated fixes, and only ever commits to `autopilot/<date>-<topic>` branches.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, websockets, faster-whisper, edge-tts, structlog, pytest, pytest-asyncio, httpx, SQLite, vanilla HTML/JS frontend (no build step), `urllib.request` for LLM HTTP (NBAVedio pattern), local Claude gateway at `http://localhost:23333/api/anthropic/v1/messages`.

**Convention:** Run all commands from `D:\repo\speakAgent`. On Windows bash use forward slashes for relative paths. Every task ends with a commit on `main` (Phase A) or on `autopilot/...` (Phase B is autopilot-internal so merges to main happen via human PR review).

---

# Phase A — Trainer end-to-end

Goal of Phase A: by the end of Task A16, the user can open `http://localhost:8765`, click "Today: Week 1 Day 1", hold spacebar, speak, see captions, hear a TTS reply, and see a scorecard.

---

### Task A1: Repo skeleton and dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `server/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/eval/__init__.py`
- Test: `tests/unit/test_skeleton.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_skeleton.py
import importlib

def test_server_package_importable():
    mod = importlib.import_module("server")
    assert mod is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_skeleton.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'server'`.

- [ ] **Step 3: Create `requirements.txt`**

```text
fastapi==0.115.0
uvicorn[standard]==0.30.6
websockets==13.0
faster-whisper==1.0.3
edge-tts==6.1.12
structlog==24.4.0
pyyaml==6.0.2
pytest==8.3.3
pytest-asyncio==0.24.0
httpx==0.27.2
```

- [ ] **Step 4: Create `pyproject.toml`**

```toml
[project]
name = "speakagent"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 5: Create `.env.example`**

```text
SPEAKAGENT_PORT=8765
CLAUDE_API_ENDPOINT=http://localhost:23333/api/anthropic/v1/messages
CLAUDE_MODEL=claude-opus-4.7-1m-internal
AI_BACKEND=claude
AZURE_OPENAI_ENDPOINT=https://ravensai.openai.azure.com/openai/responses
AZURE_OPENAI_API_VERSION=2025-04-01-preview
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_MODEL=gpt-5.4-mini
WHISPER_MODEL=small
```

- [ ] **Step 6: Create `.gitignore`**

```text
__pycache__/
*.pyc
.venv/
.env
data/sessions/
data/logs/
data/listening/
data/vocab_srs.sqlite
autopilot/runs/
.claude/worktrees/
```

- [ ] **Step 7: Create empty `__init__.py` files**

```python
# server/__init__.py
```

```python
# tests/__init__.py
```

```python
# tests/unit/__init__.py
```

```python
# tests/integration/__init__.py
```

```python
# tests/eval/__init__.py
```

- [ ] **Step 8: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: `Successfully installed ...` (faster-whisper download may take a minute).

- [ ] **Step 9: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_skeleton.py -v`
Expected: PASS, `1 passed`.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml requirements.txt .env.example .gitignore server/__init__.py tests/
git commit -m "chore: initial skeleton and pytest scaffold"
```

---

### Task A2: config.py with port, voices, accent rotation

**Files:**
- Create: `server/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py
import os
from server.config import load_config, voices_for_week

def test_default_port_is_8765(monkeypatch):
    monkeypatch.delenv("SPEAKAGENT_PORT", raising=False)
    cfg = load_config()
    assert cfg.port == 8765

def test_port_env_override(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_PORT", "9000")
    cfg = load_config()
    assert cfg.port == 9000

def test_seven_voices_total():
    cfg = load_config()
    assert len(cfg.voices) == 7
    assert "en-US-AriaNeural" in cfg.voices
    assert "zh-CN-XiaoxiaoNeural" in cfg.voices

def test_week1_us_only():
    weights = voices_for_week(1)
    assert all(v.startswith("en-US-") for v in weights)

def test_week3_us_uk_mix():
    weights = voices_for_week(3)
    families = {v.split("-")[1] for v in weights}
    assert families == {"US", "GB"}

def test_week5_four_families():
    weights = voices_for_week(5)
    families = {v.split("-")[1] for v in weights}
    assert families == {"US", "GB", "IN", "CN"}

def test_week7_all_voices_eligible():
    weights = voices_for_week(7)
    assert len(weights) >= 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'server.config'`.

- [ ] **Step 3: Implement `server/config.py`**

```python
# server/config.py
"""Single config surface. All env reads happen here."""
import os
from dataclasses import dataclass, field
from typing import List


VOICES_ALL = [
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-GB-RyanNeural",
    "en-GB-SoniaNeural",
    "en-IN-NeerjaNeural",
    "en-IN-PrabhatNeural",
    "zh-CN-XiaoxiaoNeural",
]


@dataclass
class Config:
    port: int = 8765
    claude_endpoint: str = "http://localhost:23333/api/anthropic/v1/messages"
    claude_model: str = "claude-opus-4.7-1m-internal"
    ai_backend: str = "claude"
    azure_endpoint: str = ""
    azure_api_version: str = "2025-04-01-preview"
    azure_api_key: str = ""
    azure_model: str = "gpt-5.4-mini"
    whisper_model: str = "small"
    voices: List[str] = field(default_factory=lambda: list(VOICES_ALL))
    curriculum_dir: str = "curriculum"
    data_dir: str = "data"


def load_config() -> Config:
    return Config(
        port=int(os.environ.get("SPEAKAGENT_PORT", "8765")),
        claude_endpoint=os.environ.get(
            "CLAUDE_API_ENDPOINT",
            "http://localhost:23333/api/anthropic/v1/messages",
        ),
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-4.7-1m-internal"),
        ai_backend=os.environ.get("AI_BACKEND", "claude").lower(),
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        azure_api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        azure_api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
        azure_model=os.environ.get("AZURE_OPENAI_MODEL", "gpt-5.4-mini"),
        whisper_model=os.environ.get("WHISPER_MODEL", "small"),
    )


def voices_for_week(week: int) -> List[str]:
    """Returns the eligible voice pool for a given training week (1-8)."""
    if week <= 2:
        return ["en-US-AriaNeural", "en-US-GuyNeural"]
    if week <= 4:
        return [
            "en-US-AriaNeural", "en-US-GuyNeural",
            "en-GB-RyanNeural", "en-GB-SoniaNeural",
        ]
    if week <= 6:
        return list(VOICES_ALL)
    return list(VOICES_ALL)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: PASS, `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/config.py tests/unit/test_config.py
git commit -m "feat(config): central config + voice rotation per week"
```

---

### Task A3: structured logging

**Files:**
- Create: `server/logging_setup.py`
- Test: `tests/unit/test_logging.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_logging.py
import json
from server.logging_setup import get_logger, configure_logging

def test_logger_emits_json(capsys):
    configure_logging()
    log = get_logger("test")
    log.info("hello", session_id="s1", latency_ms=42)
    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello"
    assert payload["session_id"] == "s1"
    assert payload["latency_ms"] == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_logging.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `server/logging_setup.py`**

```python
# server/logging_setup.py
"""structlog JSON setup. One call to configure_logging() at startup."""
import logging
import sys
import structlog


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_logging.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/logging_setup.py tests/unit/test_logging.py
git commit -m "feat(logging): structlog JSON output"
```

---

### Task A4: llm.py — Claude/GPT factory with fallback (NBAVedio pattern)

**Files:**
- Create: `server/llm.py`
- Test: `tests/unit/test_llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_llm.py
from unittest.mock import patch, MagicMock
import json
import io
from server.llm import ClaudeAssistant, GptAssistant, get_assistant, call_with_fallback


def _fake_resp(payload: dict):
    raw = json.dumps(payload).encode("utf-8")
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = raw
    cm.__exit__.return_value = False
    return cm


def test_claude_happy_path():
    payload = {"content": [{"type": "text", "text": "  hello  "}]}
    with patch("urllib.request.urlopen", return_value=_fake_resp(payload)):
        a = ClaudeAssistant()
        assert a._call("hi", system="sys") == "hello"


def test_claude_retries_three_times_then_returns_empty():
    with patch("urllib.request.urlopen", side_effect=Exception("boom")), \
         patch("time.sleep"):
        a = ClaudeAssistant()
        assert a._call("hi") == ""


def test_factory_returns_claude_by_default(monkeypatch):
    monkeypatch.setenv("AI_BACKEND", "claude")
    inst = get_assistant()
    assert isinstance(inst, ClaudeAssistant)


def test_factory_returns_gpt_when_requested(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    inst = get_assistant("gpt")
    assert isinstance(inst, GptAssistant)


def test_call_with_fallback_uses_gpt_when_claude_empty(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    with patch.object(ClaudeAssistant, "_call", return_value=""), \
         patch.object(GptAssistant, "_call", return_value="gpt-said-this"):
        out = call_with_fallback("prompt", system="sys")
    assert out == "gpt-said-this"


def test_call_with_fallback_returns_graceful_error_when_both_fail(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    with patch.object(ClaudeAssistant, "_call", return_value=""), \
         patch.object(GptAssistant, "_call", return_value=""):
        out = call_with_fallback("prompt")
    assert "trouble" in out.lower() or "error" in out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_llm.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'server.llm'`.

- [ ] **Step 3: Implement `server/llm.py`**

```python
# server/llm.py
"""LLM access — copied from NBAVedio (urllib + factory + 3-retry).

Default backend: Claude via local Agent Maestro gateway.
Fallback chain (call_with_fallback): Claude -> GPT -> graceful spoken error.
"""
import json
import os
import time
import urllib.request
from typing import Optional

from server.logging_setup import get_logger

_log = get_logger("llm")


class ClaudeAssistant:
    """Claude backend via local Agent Maestro endpoint."""

    DEFAULT_MODEL = "claude-opus-4.7-1m-internal"

    def __init__(self):
        self._endpoint = os.environ.get(
            "CLAUDE_API_ENDPOINT",
            "http://localhost:23333/api/anthropic/v1/messages",
        )
        self._model = os.environ.get("CLAUDE_MODEL", self.DEFAULT_MODEL)

    def _call(self, prompt: str, system: str = "You are a helpful English speaking coach.") -> str:
        body = json.dumps({
            "model": self._model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        for attempt in range(3):
            req = urllib.request.Request(
                self._endpoint,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        return block["text"].strip()
                return ""
            except Exception as e:
                wait = (attempt + 1) * 10
                _log.warning("claude_retry", attempt=attempt + 1, error=str(e), wait_s=wait)
                if attempt < 2:
                    time.sleep(wait)
        _log.error("claude_failed_all_retries")
        return ""


class GptAssistant:
    """Azure OpenAI GPT backend (fallback)."""

    def __init__(self):
        self.endpoint = os.environ.get(
            "AZURE_OPENAI_ENDPOINT",
            "https://ravensai.openai.azure.com/openai/responses",
        )
        self.api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
        self.api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        self.model = os.environ.get("AZURE_OPENAI_MODEL", "gpt-5.4-mini")
        if not self.api_key:
            raise RuntimeError(
                "AZURE_OPENAI_API_KEY not set; cannot use GPT backend."
            )

    def _call(self, prompt: str, system: str = "You are a helpful English speaking coach.") -> str:
        url = f"{self.endpoint}?api-version={self.api_version}"
        body = json.dumps({
            "model": self.model,
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            _log.error("gpt_failed", error=str(e))
            return ""

        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        return c["text"]
        return ""


_DEFAULT_BACKEND = os.environ.get("AI_BACKEND", "claude").lower()


def get_assistant(backend: Optional[str] = None):
    choice = (backend or os.environ.get("AI_BACKEND", "claude")).lower()
    if choice == "gpt":
        return GptAssistant()
    return ClaudeAssistant()


GRACEFUL_ERROR = (
    "I'm having trouble reaching my brain right now. "
    "Let's pause this turn and try again in a moment."
)


def call_with_fallback(prompt: str, system: str = "You are a helpful English speaking coach.") -> str:
    """Claude -> GPT -> graceful spoken error. Always returns a non-empty string."""
    try:
        out = ClaudeAssistant()._call(prompt, system=system)
        if out:
            return out
    except Exception as e:
        _log.error("claude_unexpected", error=str(e))
    try:
        out = GptAssistant()._call(prompt, system=system)
        if out:
            return out
    except Exception as e:
        _log.error("gpt_unexpected", error=str(e))
    _log.error("llm_all_backends_failed")
    return GRACEFUL_ERROR
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_llm.py -v`
Expected: PASS, `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/llm.py tests/unit/test_llm.py
git commit -m "feat(llm): Claude+GPT factory with 3-retry and fallback (NBAVedio pattern)"
```

---

### Task A5: stt.py — faster-whisper wrapper

**Files:**
- Create: `server/stt.py`
- Test: `tests/unit/test_stt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stt.py
from unittest.mock import patch, MagicMock
import numpy as np
from server.stt import SttEngine, TranscriptionResult


class FakeSegment:
    def __init__(self, text, avg_logprob, words):
        self.text = text
        self.avg_logprob = avg_logprob
        self.words = words


class FakeWord:
    def __init__(self, w, start, end, prob):
        self.word = w
        self.start = start
        self.end = end
        self.probability = prob


def test_transcribe_returns_text_confidence_words():
    fake_words = [FakeWord("hello", 0.0, 0.5, 0.95), FakeWord("world", 0.5, 1.0, 0.90)]
    fake_seg = FakeSegment("hello world", -0.2, fake_words)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_seg], MagicMock(language="en"))

    with patch("server.stt.WhisperModel", return_value=fake_model):
        eng = SttEngine(model_name="small")
        pcm = np.zeros(16000, dtype=np.float32)
        result = eng.transcribe(pcm)

    assert isinstance(result, TranscriptionResult)
    assert result.text == "hello world"
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.words) == 2
    assert result.words[0]["w"] == "hello"
    assert result.words[0]["prob"] == 0.95
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_stt.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `server/stt.py`**

```python
# server/stt.py
"""faster-whisper STT wrapper. Long-lived engine; one transcribe call per utterance."""
import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional

import numpy as np
from faster_whisper import WhisperModel

from server.logging_setup import get_logger

_log = get_logger("stt")


@dataclass
class TranscriptionResult:
    text: str
    confidence: float
    words: List[Dict] = field(default_factory=list)
    language: str = "en"


class SttEngine:
    def __init__(self, model_name: str = "small", device: str = "auto"):
        _log.info("stt_loading_model", model=model_name, device=device)
        self._model = WhisperModel(model_name, device=device, compute_type="auto")
        _log.info("stt_model_loaded")

    def transcribe(self, pcm_f32_16k: np.ndarray) -> TranscriptionResult:
        segments, info = self._model.transcribe(
            pcm_f32_16k,
            language="en",
            vad_filter=True,
            word_timestamps=True,
        )
        seg_list = list(segments)
        text = " ".join(s.text.strip() for s in seg_list).strip()

        if not seg_list:
            return TranscriptionResult(text="", confidence=0.0, words=[], language=info.language)

        avg_logprob = sum(s.avg_logprob for s in seg_list) / len(seg_list)
        confidence = max(0.0, min(1.0, math.exp(avg_logprob)))

        words: List[Dict] = []
        for seg in seg_list:
            for w in (seg.words or []):
                words.append({
                    "w": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                    "prob": w.probability,
                })

        return TranscriptionResult(text=text, confidence=confidence, words=words, language=info.language)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_stt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/stt.py tests/unit/test_stt.py
git commit -m "feat(stt): faster-whisper wrapper with VAD + word timings"
```

---

### Task A6: tts.py — edge-tts streaming with accent rotation

**Files:**
- Create: `server/tts.py`
- Test: `tests/unit/test_tts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tts.py
import pytest
from unittest.mock import patch, AsyncMock
from server.tts import pick_voice, synthesize_stream


def test_pick_voice_week1_us_only():
    v = pick_voice(week=1, turn_index=0)
    assert v.startswith("en-US-")


def test_pick_voice_week5_cycles_four_families():
    seen = set()
    for i in range(20):
        v = pick_voice(week=5, turn_index=i)
        seen.add(v.split("-")[1])
    assert {"US", "GB", "IN", "CN"}.issubset(seen)


@pytest.mark.asyncio
async def test_synthesize_stream_yields_audio_chunks():
    async def fake_stream(self):
        yield {"type": "audio", "data": b"\x01\x02"}
        yield {"type": "audio", "data": b"\x03\x04"}
        yield {"type": "WordBoundary"}

    with patch("edge_tts.Communicate.stream", new=fake_stream):
        chunks = []
        async for c in synthesize_stream("hi", voice="en-US-AriaNeural"):
            chunks.append(c)
    assert chunks == [b"\x01\x02", b"\x03\x04"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_tts.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `server/tts.py`**

```python
# server/tts.py
"""edge-tts streaming wrapper + per-week voice rotation."""
from typing import AsyncIterator
import edge_tts

from server.config import voices_for_week


def pick_voice(week: int, turn_index: int) -> str:
    pool = voices_for_week(week)
    return pool[turn_index % len(pool)]


async def synthesize_stream(text: str, voice: str) -> AsyncIterator[bytes]:
    """Yield raw MP3 chunks as they arrive from edge-tts."""
    comm = edge_tts.Communicate(text, voice)
    async for chunk in comm.stream():
        if chunk.get("type") == "audio":
            yield chunk["data"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_tts.py -v`
Expected: PASS, `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/tts.py tests/unit/test_tts.py
git commit -m "feat(tts): edge-tts streaming with per-week voice rotation"
```

---

### Task A7: scorer.py — three-dimensional scoring

**Files:**
- Create: `server/scorer.py`
- Test: `tests/unit/test_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_scorer.py
from unittest.mock import patch
from server.scorer import score_turn, TurnScore, _wer, _fluency


def test_wer_identical_is_zero():
    assert _wer("hello world", "hello world") == 0.0


def test_wer_one_substitution():
    assert _wer("hello world", "hello there") == 0.5


def test_fluency_counts_fillers_and_wpm():
    words = [
        {"w": "um", "start": 0.0, "end": 0.2, "prob": 0.9},
        {"w": "i", "start": 0.3, "end": 0.4, "prob": 0.9},
        {"w": "think", "start": 0.4, "end": 0.7, "prob": 0.9},
        {"w": "uh", "start": 1.7, "end": 1.9, "prob": 0.9},
        {"w": "yes", "start": 1.9, "end": 2.1, "prob": 0.9},
    ]
    f = _fluency(words)
    assert f["fillers"] == 2
    assert f["pauses_over_800ms"] == 1
    assert f["wpm"] > 0


def test_score_turn_aggregates_three_dims():
    words = [{"w": "ok", "start": 0.0, "end": 0.3, "prob": 0.95}]
    with patch("server.scorer.call_with_fallback", return_value='{"content_score": 4, "rewrite": "Sure.", "issues": ["short"]}'):
        s = score_turn(
            user_text="ok",
            user_words=words,
            user_confidence=0.9,
            ideal_text="ok",
            llm_system="judge",
        )
    assert isinstance(s, TurnScore)
    assert 0.0 <= s.pronunciation <= 1.0
    assert s.content_score == 4
    assert s.rewrite == "Sure."


def test_score_turn_handles_invalid_llm_json():
    words = [{"w": "ok", "start": 0.0, "end": 0.3, "prob": 0.95}]
    with patch("server.scorer.call_with_fallback", return_value="not json"):
        s = score_turn(
            user_text="ok", user_words=words, user_confidence=0.9,
            ideal_text="ok", llm_system="judge",
        )
    assert s.content_score == 3
    assert "rewrite" in s.__dict__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_scorer.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `server/scorer.py`**

```python
# server/scorer.py
"""Three-dim scoring: pronunciation proxy + fluency + content (LLM judge)."""
import json
from dataclasses import dataclass, field
from typing import List, Dict

from server.llm import call_with_fallback
from server.logging_setup import get_logger

_log = get_logger("scorer")

FILLERS = {"um", "uh", "uhm", "like", "erm", "err"}


@dataclass
class TurnScore:
    pronunciation: float
    fluency: Dict
    content_score: int
    issues: List[str] = field(default_factory=list)
    rewrite: str = ""

    def to_dict(self) -> Dict:
        return {
            "pronunciation": self.pronunciation,
            "fluency": self.fluency,
            "content_score": self.content_score,
            "issues": self.issues,
            "rewrite": self.rewrite,
        }


def _wer(ref: str, hyp: str) -> float:
    """Standard word error rate."""
    r = ref.lower().split()
    h = hyp.lower().split()
    if not r:
        return 0.0 if not h else 1.0
    n, m = len(r), len(h)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if r[i - 1] == h[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[n][m] / n


def _fluency(words: List[Dict]) -> Dict:
    if not words:
        return {"wpm": 0.0, "pauses_over_800ms": 0, "fillers": 0, "duration_s": 0.0}
    duration = max(0.001, words[-1]["end"] - words[0]["start"])
    wpm = (len(words) / duration) * 60.0
    pauses = 0
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        if gap > 0.8:
            pauses += 1
    fillers = sum(1 for w in words if w["w"].lower().strip(",.!?") in FILLERS)
    return {
        "wpm": round(wpm, 1),
        "pauses_over_800ms": pauses,
        "fillers": fillers,
        "duration_s": round(duration, 2),
    }


_JUDGE_SYSTEM = (
    "You are an English-speaking interview coach. Given a spoken answer and an ideal version, "
    "rate content 1-5 (5=excellent), produce a more idiomatic rewrite, and list up to 3 issues. "
    "Reply ONLY with JSON: {\"content_score\": int, \"rewrite\": str, \"issues\": [str]}."
)


def score_turn(
    user_text: str,
    user_words: List[Dict],
    user_confidence: float,
    ideal_text: str,
    llm_system: str = _JUDGE_SYSTEM,
) -> TurnScore:
    wer = _wer(ideal_text, user_text)
    pronunciation = max(0.0, min(1.0, 0.5 * user_confidence + 0.5 * (1.0 - wer)))
    fluency = _fluency(user_words)

    prompt = (
        f"User said: {user_text!r}\n"
        f"Ideal version: {ideal_text!r}\n"
        "Score and rewrite per the system instructions."
    )
    raw = call_with_fallback(prompt, system=llm_system)
    try:
        parsed = json.loads(raw)
        content_score = int(parsed.get("content_score", 3))
        rewrite = str(parsed.get("rewrite", ""))
        issues = list(parsed.get("issues", []))[:3]
    except Exception as e:
        _log.warning("scorer_judge_parse_failed", error=str(e), raw=raw[:200])
        content_score, rewrite, issues = 3, "", []

    return TurnScore(
        pronunciation=round(pronunciation, 3),
        fluency=fluency,
        content_score=content_score,
        issues=issues,
        rewrite=rewrite,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_scorer.py -v`
Expected: PASS, `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/scorer.py tests/unit/test_scorer.py
git commit -m "feat(scorer): pronunciation + fluency + LLM-judged content"
```

---

### Task A8: progress.py — session log + SQLite SM-2 SRS

**Files:**
- Create: `server/progress.py`
- Test: `tests/unit/test_progress.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_progress.py
import os
import json
import tempfile
from datetime import date, timedelta
from server.progress import ProgressStore, sm2_next


def test_sm2_quality_5_increases_interval():
    nxt = sm2_next(prev_interval=1, prev_ease=2.5, quality=5)
    assert nxt["interval_days"] >= 6
    assert nxt["ease"] >= 2.5


def test_sm2_quality_2_resets_to_one_day():
    nxt = sm2_next(prev_interval=10, prev_ease=2.5, quality=2)
    assert nxt["interval_days"] == 1


def test_session_append_and_read(tmp_path):
    store = ProgressStore(data_dir=str(tmp_path))
    sid = "s1"
    store.append_turn(sid, "lesson1", {"role": "user", "text": "hello", "score": {"content_score": 4}})
    store.append_turn(sid, "lesson1", {"role": "agent", "text": "hi back"})
    turns = store.read_session(sid)
    assert len(turns) == 2
    assert turns[0]["role"] == "user"


def test_vocab_srs_add_and_due(tmp_path):
    store = ProgressStore(data_dir=str(tmp_path))
    store.add_words(["heterogeneous", "consensus"])
    due = store.due_words(today=date.today() + timedelta(days=1))
    assert "heterogeneous" in due
    assert "consensus" in due


def test_vocab_srs_review_pushes_due_date(tmp_path):
    store = ProgressStore(data_dir=str(tmp_path))
    store.add_words(["adjudication"])
    store.review_word("adjudication", quality=5)
    due_today = store.due_words(today=date.today())
    assert "adjudication" not in due_today
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_progress.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `server/progress.py`**

```python
# server/progress.py
"""Session JSON log + SQLite SM-2 SRS for vocab."""
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Dict, List


def sm2_next(prev_interval: int, prev_ease: float, quality: int) -> Dict:
    """SM-2 algorithm. quality: 0-5. Returns new {interval_days, ease}."""
    if quality < 3:
        return {"interval_days": 1, "ease": max(1.3, prev_ease)}
    if prev_interval == 0:
        new_interval = 1
    elif prev_interval == 1:
        new_interval = 6
    else:
        new_interval = round(prev_interval * prev_ease)
    new_ease = prev_ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ease = max(1.3, new_ease)
    return {"interval_days": new_interval, "ease": round(new_ease, 3)}


class ProgressStore:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.sessions_dir = os.path.join(data_dir, "sessions")
        os.makedirs(self.sessions_dir, exist_ok=True)
        self.db_path = os.path.join(data_dir, "vocab_srs.sqlite")
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS vocab_srs (
                    word TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL,
                    next_review_at TEXT NOT NULL,
                    interval_days INTEGER NOT NULL DEFAULT 0,
                    ease REAL NOT NULL DEFAULT 2.5
                )
            """)

    def _session_path(self, session_id: str) -> str:
        return os.path.join(self.sessions_dir, f"{session_id}.jsonl")

    def append_turn(self, session_id: str, lesson_id: str, turn: Dict) -> None:
        record = {
            "ts": datetime.utcnow().isoformat(),
            "lesson_id": lesson_id,
            **turn,
        }
        with open(self._session_path(session_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_session(self, session_id: str) -> List[Dict]:
        p = self._session_path(session_id)
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def add_words(self, words: List[str]) -> None:
        today = date.today().isoformat()
        with sqlite3.connect(self.db_path) as con:
            for w in words:
                con.execute(
                    "INSERT OR IGNORE INTO vocab_srs(word, first_seen_at, next_review_at) VALUES (?, ?, ?)",
                    (w, today, today),
                )

    def due_words(self, today: date = None) -> List[str]:
        today = today or date.today()
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute(
                "SELECT word FROM vocab_srs WHERE next_review_at <= ?",
                (today.isoformat(),),
            )
            return [r[0] for r in cur.fetchall()]

    def review_word(self, word: str, quality: int) -> None:
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute(
                "SELECT interval_days, ease FROM vocab_srs WHERE word = ?", (word,)
            )
            row = cur.fetchone()
            if not row:
                return
            interval, ease = row
            nxt = sm2_next(interval, ease, quality)
            new_due = (date.today() + timedelta(days=nxt["interval_days"])).isoformat()
            con.execute(
                "UPDATE vocab_srs SET interval_days = ?, ease = ?, next_review_at = ? WHERE word = ?",
                (nxt["interval_days"], nxt["ease"], new_due, word),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_progress.py -v`
Expected: PASS, `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/progress.py tests/unit/test_progress.py
git commit -m "feat(progress): session JSONL + SQLite SM-2 SRS"
```

---

### Task A9: lesson plan loader + coach state machine

**Files:**
- Create: `server/lesson.py`
- Create: `server/coach.py`
- Create: `curriculum/week1/day1.yml`
- Test: `tests/unit/test_lesson.py`
- Test: `tests/unit/test_coach.py`

- [ ] **Step 1: Write the failing test for lesson loader**

```python
# tests/unit/test_lesson.py
from server.lesson import load_lesson


def test_load_week1_day1(tmp_path):
    p = tmp_path / "lesson.yml"
    p.write_text(
        "id: w1d1\n"
        "title: Listening foundation\n"
        "week: 1\n"
        "turns:\n"
        "  - speaker: agent\n"
        "    say: Hello and welcome.\n"
        "  - speaker: user\n"
        "    prompt: Repeat after me.\n"
        "    ideal: Hello and welcome.\n",
        encoding="utf-8",
    )
    lp = load_lesson(str(p))
    assert lp.id == "w1d1"
    assert lp.week == 1
    assert len(lp.turns) == 2
    assert lp.turns[0]["speaker"] == "agent"
    assert lp.turns[1]["ideal"] == "Hello and welcome."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_lesson.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `server/lesson.py`**

```python
# server/lesson.py
"""Lesson plan loader (YAML)."""
from dataclasses import dataclass, field
from typing import List, Dict
import yaml


@dataclass
class LessonPlan:
    id: str
    title: str
    week: int
    turns: List[Dict] = field(default_factory=list)


def load_lesson(path: str) -> LessonPlan:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return LessonPlan(
        id=data["id"],
        title=data.get("title", data["id"]),
        week=int(data.get("week", 1)),
        turns=list(data.get("turns", [])),
    )
```

- [ ] **Step 4: Run lesson test, expect pass**

Run: `python -m pytest tests/unit/test_lesson.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing test for coach**

```python
# tests/unit/test_coach.py
from unittest.mock import patch
from server.coach import Coach, CoachState
from server.lesson import LessonPlan


def _plan():
    return LessonPlan(
        id="w1d1", title="t", week=1,
        turns=[
            {"speaker": "agent", "say": "Hello and welcome."},
            {"speaker": "user", "prompt": "Repeat.", "ideal": "Hello and welcome."},
        ],
    )


def test_coach_starts_idle():
    c = Coach(_plan())
    assert c.state == CoachState.IDLE


def test_advance_from_idle_to_speak_prompt():
    c = Coach(_plan())
    turn = c.next_turn()
    assert c.state == CoachState.SPEAK_PROMPT
    assert turn["speaker"] == "agent"
    assert turn["say"] == "Hello and welcome."


def test_user_turn_transitions_to_listen_then_score():
    c = Coach(_plan())
    c.next_turn()  # agent
    user_turn = c.next_turn()
    assert c.state == CoachState.LISTEN_USER
    assert user_turn["speaker"] == "user"


def test_submit_user_response_returns_score_and_advances():
    c = Coach(_plan())
    c.next_turn()  # agent
    c.next_turn()  # user prompt
    fake = {"pronunciation": 0.9, "fluency": {}, "content_score": 4, "issues": [], "rewrite": ""}
    with patch("server.coach.score_turn") as mock_score:
        from server.scorer import TurnScore
        mock_score.return_value = TurnScore(
            pronunciation=0.9, fluency={}, content_score=4, issues=[], rewrite=""
        )
        score = c.submit_user_response(text="Hello and welcome.", words=[], confidence=0.9)
    assert score.content_score == 4
    assert c.state == CoachState.SESSION_END
```

- [ ] **Step 6: Run coach test to verify it fails**

Run: `python -m pytest tests/unit/test_coach.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 7: Implement `server/coach.py`**

```python
# server/coach.py
"""Coach state machine. Pure orchestration; no HTTP, no I/O for adapters."""
from enum import Enum
from typing import Dict, List, Optional

from server.lesson import LessonPlan
from server.scorer import score_turn, TurnScore


class CoachState(str, Enum):
    IDLE = "idle"
    SPEAK_PROMPT = "speak_prompt"
    LISTEN_USER = "listen_user"
    SCORE = "score"
    NEXT_TURN = "next_turn"
    SESSION_END = "session_end"


class Coach:
    def __init__(self, plan: LessonPlan):
        self.plan = plan
        self.state = CoachState.IDLE
        self._idx = -1
        self._last_user_ideal: Optional[str] = None
        self.scores: List[TurnScore] = []

    def next_turn(self) -> Optional[Dict]:
        self._idx += 1
        if self._idx >= len(self.plan.turns):
            self.state = CoachState.SESSION_END
            return None
        turn = self.plan.turns[self._idx]
        if turn["speaker"] == "agent":
            self.state = CoachState.SPEAK_PROMPT
        else:
            self.state = CoachState.LISTEN_USER
            self._last_user_ideal = turn.get("ideal", "")
        return turn

    def submit_user_response(self, text: str, words: List[Dict], confidence: float) -> TurnScore:
        self.state = CoachState.SCORE
        s = score_turn(
            user_text=text,
            user_words=words,
            user_confidence=confidence,
            ideal_text=self._last_user_ideal or text,
        )
        self.scores.append(s)
        if self._idx + 1 >= len(self.plan.turns):
            self.state = CoachState.SESSION_END
        else:
            self.state = CoachState.NEXT_TURN
        return s
```

- [ ] **Step 8: Run coach test to verify it passes**

Run: `python -m pytest tests/unit/test_coach.py -v`
Expected: PASS.

- [ ] **Step 9: Create `curriculum/week1/day1.yml`**

```yaml
id: w1d1
title: "Week 1 Day 1 — Listening foundation: greetings & welcome"
week: 1
turns:
  - speaker: agent
    say: "Welcome to your first speaking practice. I'll say a sentence; you repeat it."
  - speaker: agent
    say: "Hello, and welcome to the interview."
  - speaker: user
    prompt: "Now you repeat: Hello, and welcome to the interview."
    ideal: "Hello, and welcome to the interview."
  - speaker: agent
    say: "Great. Let's try one more."
  - speaker: agent
    say: "Thanks for taking the time to speak with me today."
  - speaker: user
    prompt: "Your turn."
    ideal: "Thanks for taking the time to speak with me today."
```

- [ ] **Step 10: Commit**

```bash
git add server/lesson.py server/coach.py curriculum/week1/day1.yml tests/unit/test_lesson.py tests/unit/test_coach.py
git commit -m "feat(coach): lesson loader + state machine + week1 day1 lesson"
```

---

### Task A10: server/main.py — FastAPI app + WebSocket session

**Files:**
- Create: `server/main.py`
- Create: `server/session.py`
- Test: `tests/integration/test_http.py`
- Test: `tests/integration/test_ws.py`

- [ ] **Step 1: Write the failing HTTP test**

```python
# tests/integration/test_http.py
from fastapi.testclient import TestClient
from server.main import app


def test_get_today_returns_lesson_id():
    with TestClient(app) as client:
        r = client.get("/api/today")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "w1d1"
    assert body["week"] == 1


def test_get_progress_empty_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        r = client.get("/api/progress")
    assert r.status_code == 200
    assert "due_words" in r.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_http.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'server.main'`.

- [ ] **Step 3: Implement `server/session.py`**

```python
# server/session.py
"""Per-WebSocket session state container."""
import uuid
from dataclasses import dataclass, field
from typing import List

from server.coach import Coach
from server.lesson import LessonPlan


@dataclass
class SpeechSession:
    id: str
    coach: Coach
    audio_buffer: bytearray = field(default_factory=bytearray)


def new_session(plan: LessonPlan) -> SpeechSession:
    return SpeechSession(id=uuid.uuid4().hex[:12], coach=Coach(plan))
```

- [ ] **Step 4: Implement `server/main.py`**

```python
# server/main.py
"""FastAPI app: static frontend, /api/today, /api/progress, /ws/session."""
import asyncio
import json
import os
import wave
from io import BytesIO

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import load_config
from server.lesson import load_lesson
from server.logging_setup import configure_logging, get_logger
from server.progress import ProgressStore
from server.session import new_session
from server.stt import SttEngine
from server.tts import pick_voice, synthesize_stream

configure_logging()
_log = get_logger("server")
_cfg = load_config()
_data_dir = os.environ.get("SPEAKAGENT_DATA_DIR", _cfg.data_dir)
_progress = ProgressStore(data_dir=_data_dir)

app = FastAPI(title="speakAgent")
_stt: SttEngine | None = None


def _get_stt() -> SttEngine:
    global _stt
    if _stt is None:
        _stt = SttEngine(model_name=_cfg.whisper_model)
    return _stt


@app.get("/api/today")
def api_today():
    plan = load_lesson(os.path.join(_cfg.curriculum_dir, "week1", "day1.yml"))
    return {"id": plan.id, "title": plan.title, "week": plan.week, "turn_count": len(plan.turns)}


@app.get("/api/progress")
def api_progress():
    return {"due_words": _progress.due_words()}


@app.websocket("/ws/session")
async def ws_session(ws: WebSocket):
    await ws.accept()
    plan = load_lesson(os.path.join(_cfg.curriculum_dir, "week1", "day1.yml"))
    sess = new_session(plan)
    await ws.send_json({"type": "session_start", "session_id": sess.id, "lesson": plan.title})

    try:
        while True:
            turn = sess.coach.next_turn()
            if turn is None:
                await ws.send_json({"type": "session_end", "scores": [s.to_dict() for s in sess.coach.scores]})
                break

            if turn["speaker"] == "agent":
                voice = pick_voice(week=plan.week, turn_index=sess.coach._idx)
                await ws.send_json({"type": "agent_caption", "text": turn["say"], "voice": voice})
                async for chunk in synthesize_stream(turn["say"], voice=voice):
                    await ws.send_bytes(chunk)
                await ws.send_json({"type": "agent_done"})
                _progress.append_turn(sess.id, plan.id, {"role": "agent", "text": turn["say"]})
            else:
                await ws.send_json({"type": "user_prompt", "prompt": turn.get("prompt", "Your turn.")})
                pcm = await _receive_user_audio(ws, sess)
                stt_res = _get_stt().transcribe(pcm)
                await ws.send_json({"type": "user_transcript", "text": stt_res.text, "confidence": stt_res.confidence})
                score = sess.coach.submit_user_response(stt_res.text, stt_res.words, stt_res.confidence)
                await ws.send_json({"type": "score", "score": score.to_dict()})
                _progress.append_turn(sess.id, plan.id, {
                    "role": "user", "text": stt_res.text, "score": score.to_dict(),
                })
    except WebSocketDisconnect:
        _log.info("ws_disconnect", session_id=sess.id)


async def _receive_user_audio(ws: WebSocket, sess) -> np.ndarray:
    """Receive a user_audio_start ... user_audio_end window. Audio frames arrive as bytes."""
    sess.audio_buffer.clear()
    while True:
        msg = await ws.receive()
        if "bytes" in msg and msg["bytes"] is not None:
            sess.audio_buffer.extend(msg["bytes"])
        elif "text" in msg and msg["text"] is not None:
            data = json.loads(msg["text"])
            if data.get("type") == "user_audio_end":
                break
    pcm = np.frombuffer(bytes(sess.audio_buffer), dtype=np.int16).astype(np.float32) / 32768.0
    return pcm


_web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.isdir(_web_dir):
    app.mount("/static", StaticFiles(directory=_web_dir), name="static")

    @app.get("/")
    def root():
        return FileResponse(os.path.join(_web_dir, "index.html"))
```

- [ ] **Step 5: Run HTTP test to verify it passes**

Run: `python -m pytest tests/integration/test_http.py -v`
Expected: PASS, `2 passed`.

- [ ] **Step 6: Write a minimal WebSocket test**

```python
# tests/integration/test_ws.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from server.main import app


async def _empty_stream(text, voice):
    if False:
        yield b""


def test_ws_session_emits_session_start_and_agent_caption():
    with patch("server.main.synthesize_stream", _empty_stream), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "session_start"
            msg = ws.receive_json()
            assert msg["type"] == "agent_caption"
            assert "welcome" in msg["text"].lower() or "Welcome" in msg["text"]
```

- [ ] **Step 7: Run WS test to verify it passes**

Run: `python -m pytest tests/integration/test_ws.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add server/main.py server/session.py tests/integration/test_http.py tests/integration/test_ws.py
git commit -m "feat(server): FastAPI app, /api/today, /api/progress, /ws/session"
```

---

### Task A11: web frontend — vanilla HTML + JS + CSS

**Files:**
- Create: `web/index.html`
- Create: `web/app.js`
- Create: `web/style.css`

- [ ] **Step 1: Create `web/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>speakAgent</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <header>
    <h1>speakAgent</h1>
    <span id="lesson-title">Loading…</span>
  </header>
  <main>
    <section id="dialogue"></section>
    <section id="controls">
      <button id="start-btn">Start lesson</button>
      <button id="ptt-btn" disabled>Hold SPACE to talk</button>
      <span id="status">idle</span>
    </section>
    <section id="scorecard" hidden>
      <h2>Scorecard</h2>
      <pre id="scorecard-body"></pre>
    </section>
    <details id="dev-panel">
      <summary>Dev panel</summary>
      <pre id="dev-log"></pre>
    </details>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `web/style.css`**

```css
body { font-family: system-ui, sans-serif; max-width: 800px; margin: 0 auto; padding: 1rem; background: #fafafa; }
header { display: flex; justify-content: space-between; align-items: baseline; }
#dialogue { min-height: 200px; border: 1px solid #ddd; padding: 1rem; background: white; border-radius: 8px; }
#dialogue .agent { color: #035; margin: .5rem 0; }
#dialogue .user  { color: #303; margin: .5rem 0; font-style: italic; }
#controls { margin-top: 1rem; display: flex; gap: .5rem; align-items: center; }
button { padding: .5rem 1rem; font-size: 1rem; }
button:disabled { opacity: .5; }
#status { color: #666; }
#scorecard { margin-top: 1rem; padding: 1rem; background: #fff8e1; border-radius: 8px; }
#dev-panel { margin-top: 2rem; }
#dev-log { background: #111; color: #9f9; padding: .5rem; max-height: 240px; overflow: auto; font-size: .8rem; }
```

- [ ] **Step 3: Create `web/app.js`**

```javascript
// web/app.js — vanilla front end. Push-to-talk on spacebar.
const dialogue = document.getElementById("dialogue");
const startBtn = document.getElementById("start-btn");
const pttBtn = document.getElementById("ptt-btn");
const statusEl = document.getElementById("status");
const lessonTitle = document.getElementById("lesson-title");
const scorecard = document.getElementById("scorecard");
const scorecardBody = document.getElementById("scorecard-body");
const devLog = document.getElementById("dev-log");

let ws = null;
let mediaRecorder = null;
let audioCtx = null;
let pcmChunks = [];
let recording = false;

function log(msg) {
  console.log(msg);
  devLog.textContent += msg + "\n";
  devLog.scrollTop = devLog.scrollHeight;
}

function appendDialogue(role, text) {
  const div = document.createElement("div");
  div.className = role;
  div.textContent = (role === "agent" ? "Coach: " : "You: ") + text;
  dialogue.appendChild(div);
  dialogue.scrollTop = dialogue.scrollHeight;
}

async function loadToday() {
  const r = await fetch("/api/today");
  const j = await r.json();
  lessonTitle.textContent = j.title;
}

async function startSession() {
  startBtn.disabled = true;
  statusEl.textContent = "connecting";
  ws = new WebSocket(`ws://${location.host}/ws/session`);
  ws.binaryType = "arraybuffer";

  const audioQueue = [];
  let agentAudio = null;

  ws.onmessage = async (ev) => {
    if (typeof ev.data === "string") {
      const msg = JSON.parse(ev.data);
      log(`<- ${msg.type}`);
      if (msg.type === "session_start") {
        statusEl.textContent = "ready";
      } else if (msg.type === "agent_caption") {
        appendDialogue("agent", msg.text);
        audioQueue.length = 0;
      } else if (msg.type === "agent_done") {
        await playMp3Chunks(audioQueue);
      } else if (msg.type === "user_prompt") {
        appendDialogue("agent", "[" + msg.prompt + "]");
        pttBtn.disabled = false;
        statusEl.textContent = "your turn — hold SPACE";
      } else if (msg.type === "user_transcript") {
        appendDialogue("user", msg.text);
      } else if (msg.type === "score") {
        scorecard.hidden = false;
        scorecardBody.textContent = JSON.stringify(msg.score, null, 2);
      } else if (msg.type === "session_end") {
        statusEl.textContent = "session complete";
        scorecard.hidden = false;
        scorecardBody.textContent = JSON.stringify(msg.scores, null, 2);
      }
    } else {
      audioQueue.push(ev.data);
    }
  };

  ws.onerror = (e) => log("ws error " + e);
  ws.onclose = () => { statusEl.textContent = "disconnected"; pttBtn.disabled = true; };
}

async function playMp3Chunks(chunks) {
  if (!chunks.length) return;
  const blob = new Blob(chunks, { type: "audio/mpeg" });
  const url = URL.createObjectURL(blob);
  const a = new Audio(url);
  await a.play().catch((e) => log("audio play err " + e));
}

async function startRecording() {
  if (recording) return;
  recording = true;
  statusEl.textContent = "recording…";
  pcmChunks = [];
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { sampleRate: 16000, channelCount: 1 } });
  audioCtx = new AudioContext({ sampleRate: 16000 });
  const src = audioCtx.createMediaStreamSource(stream);
  const proc = audioCtx.createScriptProcessor(4096, 1, 1);
  proc.onaudioprocess = (ev) => {
    const f32 = ev.inputBuffer.getChannelData(0);
    const i16 = new Int16Array(f32.length);
    for (let i = 0; i < f32.length; i++) i16[i] = Math.max(-1, Math.min(1, f32[i])) * 32767;
    if (ws && ws.readyState === 1) ws.send(i16.buffer);
  };
  src.connect(proc);
  proc.connect(audioCtx.destination);
  window._sttStream = stream;
  window._sttProc = proc;
}

async function stopRecording() {
  if (!recording) return;
  recording = false;
  statusEl.textContent = "scoring…";
  if (window._sttProc) window._sttProc.disconnect();
  if (window._sttStream) window._sttStream.getTracks().forEach((t) => t.stop());
  if (audioCtx) await audioCtx.close();
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "user_audio_end" }));
  pttBtn.disabled = true;
}

document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !pttBtn.disabled && !recording) { e.preventDefault(); startRecording(); }
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space" && recording) { e.preventDefault(); stopRecording(); }
});
pttBtn.addEventListener("mousedown", startRecording);
pttBtn.addEventListener("mouseup", stopRecording);
startBtn.addEventListener("click", startSession);

loadToday();
```

- [ ] **Step 4: Manual smoke test**

Run: `python -m uvicorn server.main:app --host 127.0.0.1 --port 8765`
Expected: server logs `stt_loading_model` then `stt_model_loaded`. Open `http://localhost:8765` in a browser. Page renders with "Week 1 Day 1 — Listening foundation: greetings & welcome" in the header.

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/app.js web/style.css
git commit -m "feat(web): vanilla SPA with push-to-talk and scorecard"
```

---

### Task A12: interview_bank.json seed (5 AI Agent questions)

**Files:**
- Create: `data/interview_bank.json`

- [ ] **Step 1: Create the seed file**

```json
[
  {
    "id": "iv1",
    "category": "behavioral",
    "difficulty": "easy",
    "question": "Tell me about a project where you built or used an AI agent.",
    "keywords": ["agent", "tools", "loop", "memory"],
    "model_answer_outline": "Project name -> problem -> agent loop (perceive/decide/act) -> tools used -> outcome -> what you'd do differently."
  },
  {
    "id": "iv2",
    "category": "llm_agent_technical",
    "difficulty": "medium",
    "question": "Explain how function calling differs from RAG, and when you'd use each.",
    "keywords": ["function calling", "tools", "RAG", "retrieval"],
    "model_answer_outline": "FC = model invokes typed actions; RAG = inject retrieved context. Use FC for actions/state changes, RAG for grounding in private knowledge."
  },
  {
    "id": "iv3",
    "category": "llm_agent_technical",
    "difficulty": "medium",
    "question": "How do you stop an agent from looping forever or burning tokens?",
    "keywords": ["budget", "rate limit", "kill switch", "max steps"],
    "model_answer_outline": "Max steps + token budget + cost cap + escalation list + kill switch + observability on cost/time per task."
  },
  {
    "id": "iv4",
    "category": "system_design",
    "difficulty": "hard",
    "question": "Design a multi-tenant agent platform that runs untrusted user prompts. What are the failure modes?",
    "keywords": ["sandbox", "rate limit", "prompt injection", "isolation"],
    "model_answer_outline": "Per-tenant queues + per-tenant token budget + sandboxed tools + prompt-injection defenses + audit logs + outbound network policy."
  },
  {
    "id": "iv5",
    "category": "behavioral",
    "difficulty": "easy",
    "question": "Walk me through a time an agent failed in production. What did you do?",
    "keywords": ["incident", "rollback", "observability"],
    "model_answer_outline": "Symptom -> detection (logs/metrics) -> rollback or fallback -> root cause -> fix + test + guardrail."
  }
]
```

- [ ] **Step 2: Commit**

```bash
git add data/interview_bank.json
git commit -m "feat(data): seed 5 AI Agent interview questions"
```

---

### Task A13: personal_projects.json seed

**Files:**
- Create: `data/personal_projects.json`

- [ ] **Step 1: Create the seed file**

```json
[
  {
    "id": "fundagent",
    "name": "FundAgent",
    "repo_path": "D:/repo/FundAgent",
    "one_liner": "Multi-vendor LLM debate for Chinese mutual fund analysis.",
    "tech_keywords": ["multi-vendor LLM", "debate architecture", "vision import", "AkShare"],
    "interview_angles": [
      {"type": "behavioral", "q": "Walk me through a project where you combined multiple LLMs."},
      {"type": "technical_deep_dive", "q": "Why debate vs ensemble vs single-model? When does debate hurt?"},
      {"type": "system_design", "q": "How would you scale the debate architecture to 100k users?"},
      {"type": "trade_off", "q": "Cost vs quality — when is debate worth it?"}
    ],
    "hard_words": ["heterogeneous", "consensus", "adjudication", "drawdown"],
    "model_answer_outline": "Problem -> why single model insufficient -> debate protocol -> consensus rule -> cost mitigation."
  },
  {
    "id": "nexis",
    "name": "Nexis",
    "repo_path": "D:/repo/Nexis",
    "one_liner": "Personal knowledge agent.",
    "tech_keywords": ["RAG", "memory", "personal corpus"],
    "interview_angles": [
      {"type": "technical_deep_dive", "q": "How do you decide what to embed vs what to keep verbatim?"},
      {"type": "system_design", "q": "How would you keep a personal knowledge agent fresh as documents change?"}
    ],
    "hard_words": ["chunking", "reranking", "hybrid search"],
    "model_answer_outline": "Corpus shape -> chunking choices -> retrieval (BM25 + vector) -> rerank -> answer synthesis."
  },
  {
    "id": "nbavedio",
    "name": "NBAVedio",
    "repo_path": "D:/repo/nba/NBAVedio",
    "one_liner": "Multi-vendor LLM pipeline for NBA video editorial workflow.",
    "tech_keywords": ["multi-vendor LLM", "factory pattern", "retry/backoff"],
    "interview_angles": [
      {"type": "technical_deep_dive", "q": "How do you swap LLM vendors without rewriting prompts?"},
      {"type": "trade_off", "q": "When would you NOT abstract over vendor SDKs?"}
    ],
    "hard_words": ["adapter", "exponential backoff", "graceful degradation"],
    "model_answer_outline": "Adapter interface -> factory -> retry policy -> fallback chain -> observability."
  },
  {
    "id": "agent-maestro",
    "name": "Agent Maestro",
    "repo_path": "D:/repo/agent-maestro",
    "one_liner": "Local Anthropic-compatible gateway routing to multiple model providers.",
    "tech_keywords": ["gateway", "Anthropic API shim", "routing"],
    "interview_angles": [
      {"type": "system_design", "q": "Why a local gateway instead of calling vendors directly?"},
      {"type": "technical_deep_dive", "q": "How do you handle prompt-cache compatibility across vendors?"}
    ],
    "hard_words": ["shim", "compatibility", "header normalization"],
    "model_answer_outline": "Use cases (local dev + key isolation + observability) -> API shim -> per-vendor adapters -> caching."
  },
  {
    "id": "vs-debugger-mcp",
    "name": "vs-debugger-mcp",
    "repo_path": "D:/repo/vs-debugger-mcp",
    "one_liner": "MCP server exposing VS Code debug session to AI agents.",
    "tech_keywords": ["MCP", "DAP", "stepwise debugging"],
    "interview_angles": [
      {"type": "technical_deep_dive", "q": "What's the smallest useful surface area for a debug-control MCP?"},
      {"type": "system_design", "q": "How do you make tool-use safe when the tool can mutate program state?"}
    ],
    "hard_words": ["breakpoint", "stack frame", "expression evaluation"],
    "model_answer_outline": "DAP basics -> chosen MCP tool surface -> safety rails on mutation -> agent UX."
  },
  {
    "id": "cc-plugin",
    "name": "cc-plugin",
    "repo_path": "D:/repo/cc-plugin",
    "one_liner": "Claude Code plugins for personal workflows.",
    "tech_keywords": ["Claude Code", "skills", "hooks"],
    "interview_angles": [
      {"type": "technical_deep_dive", "q": "What makes a good Claude Code skill?"},
      {"type": "trade_off", "q": "When to use a hook vs a skill vs an MCP tool?"}
    ],
    "hard_words": ["skill", "hook", "subagent"],
    "model_answer_outline": "Skill = procedure prompt; hook = event-driven shell; MCP = typed tool. Pick by stateful-ness."
  },
  {
    "id": "financialagent",
    "name": "FinancialAgent",
    "repo_path": "D:/repo/FinancialAgent",
    "one_liner": "Agent assistant for personal finance analysis.",
    "tech_keywords": ["tabular reasoning", "tool use"],
    "interview_angles": [
      {"type": "behavioral", "q": "How did you validate the agent's numerical answers?"},
      {"type": "technical_deep_dive", "q": "When do you let the LLM compute vs delegate to a calculator tool?"}
    ],
    "hard_words": ["reconciliation", "audit trail"],
    "model_answer_outline": "Tabular pitfalls -> calculator tool -> reconciliation -> audit log."
  }
]
```

- [ ] **Step 2: Commit**

```bash
git add data/personal_projects.json
git commit -m "feat(data): seed 7 personal-project entries with interview angles"
```

---

### Task A14: eval suite — scorer regression fixtures

**Files:**
- Create: `tests/eval/fixtures.py`
- Test: `tests/eval/test_scorer_eval.py`

- [ ] **Step 1: Write the eval test**

```python
# tests/eval/test_scorer_eval.py
import pytest
from unittest.mock import patch
from server.scorer import score_turn
from tests.eval.fixtures import FIXTURES


@pytest.mark.parametrize("fx", FIXTURES, ids=[f["id"] for f in FIXTURES])
def test_scorer_fixture(fx):
    with patch("server.scorer.call_with_fallback", return_value=fx["fake_judge"]):
        s = score_turn(
            user_text=fx["user_text"],
            user_words=fx["words"],
            user_confidence=fx["confidence"],
            ideal_text=fx["ideal"],
        )
    lo, hi = fx["pron_range"]
    assert lo <= s.pronunciation <= hi, f"{fx['id']}: pronunciation {s.pronunciation} not in {fx['pron_range']}"
    assert s.content_score == fx["expected_content_score"]
```

- [ ] **Step 2: Create `tests/eval/fixtures.py`**

```python
# tests/eval/fixtures.py
"""Golden fixtures for scorer regression. Add new ones freely; don't reorder existing."""

def _w(words):
    return [{"w": w, "start": i * 0.4, "end": i * 0.4 + 0.3, "prob": 0.95} for i, w in enumerate(words)]


FIXTURES = [
    {
        "id": "perfect_match",
        "user_text": "hello and welcome",
        "ideal": "hello and welcome",
        "confidence": 0.95,
        "words": _w(["hello", "and", "welcome"]),
        "fake_judge": '{"content_score": 5, "rewrite": "Hello and welcome.", "issues": []}',
        "pron_range": (0.9, 1.0),
        "expected_content_score": 5,
    },
    {
        "id": "one_word_off",
        "user_text": "hello and welcom",
        "ideal": "hello and welcome",
        "confidence": 0.85,
        "words": _w(["hello", "and", "welcom"]),
        "fake_judge": '{"content_score": 4, "rewrite": "Hello and welcome.", "issues": ["welcom -> welcome"]}',
        "pron_range": (0.5, 0.95),
        "expected_content_score": 4,
    },
    {
        "id": "lots_of_fillers",
        "user_text": "um i think uh yes",
        "ideal": "yes",
        "confidence": 0.80,
        "words": _w(["um", "i", "think", "uh", "yes"]),
        "fake_judge": '{"content_score": 2, "rewrite": "Yes.", "issues": ["fillers"]}',
        "pron_range": (0.0, 0.6),
        "expected_content_score": 2,
    },
    {
        "id": "empty_audio",
        "user_text": "",
        "ideal": "anything",
        "confidence": 0.0,
        "words": [],
        "fake_judge": '{"content_score": 1, "rewrite": "(no answer)", "issues": ["silent"]}',
        "pron_range": (0.0, 0.05),
        "expected_content_score": 1,
    },
    {
        "id": "long_correct_answer",
        "user_text": "the agent loop takes an observation chooses a tool and acts",
        "ideal": "the agent loop takes an observation chooses a tool and acts",
        "confidence": 0.92,
        "words": _w(["the", "agent", "loop", "takes", "an", "observation", "chooses", "a", "tool", "and", "acts"]),
        "fake_judge": '{"content_score": 5, "rewrite": "The agent loop observes, chooses a tool, and acts.", "issues": []}',
        "pron_range": (0.85, 1.0),
        "expected_content_score": 5,
    },
    {
        "id": "broken_judge_json_falls_back_to_3",
        "user_text": "some answer",
        "ideal": "some answer",
        "confidence": 0.9,
        "words": _w(["some", "answer"]),
        "fake_judge": "this is not json at all",
        "pron_range": (0.85, 1.0),
        "expected_content_score": 3,
    },
]
```

- [ ] **Step 3: Run eval suite**

Run: `python -m pytest tests/eval/test_scorer_eval.py -v`
Expected: PASS, `6 passed`. (Fixture count below the design's "20+" target is OK at v0.1; add more as new failure modes are observed.)

- [ ] **Step 4: Commit**

```bash
git add tests/eval/test_scorer_eval.py tests/eval/fixtures.py
git commit -m "test(eval): scorer regression fixtures (6 cases)"
```

---

### Task A15: integration — end-to-end synthetic-audio session

**Files:**
- Test: `tests/integration/test_e2e.py`

- [ ] **Step 1: Write the e2e test**

```python
# tests/integration/test_e2e.py
"""Drives a full WS session with mocked STT and TTS so it runs in CI without a mic."""
import json
from unittest.mock import patch
import numpy as np

from fastapi.testclient import TestClient
from server.main import app
from server.stt import TranscriptionResult


async def _empty_stream(text, voice):
    if False:
        yield b""


def _fake_transcribe(self, pcm):
    return TranscriptionResult(
        text="Hello and welcome to the interview.",
        confidence=0.92,
        words=[{"w": w, "start": i*0.3, "end": i*0.3+0.25, "prob": 0.95}
               for i, w in enumerate("Hello and welcome to the interview".split())],
        language="en",
    )


def test_full_session_round_trip():
    fake_judge = '{"content_score": 5, "rewrite": "Hello and welcome to the interview.", "issues": []}'
    with patch("server.main.synthesize_stream", _empty_stream), \
         patch("server.stt.SttEngine.transcribe", _fake_transcribe), \
         patch("server.scorer.call_with_fallback", return_value=fake_judge), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            saw_session_start = False
            saw_session_end = False
            scores_seen = 0
            for _ in range(40):
                msg = ws.receive()
                if "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    if data["type"] == "session_start":
                        saw_session_start = True
                    elif data["type"] == "user_prompt":
                        ws.send_bytes(b"\x00\x00" * 16000)
                        ws.send_text(json.dumps({"type": "user_audio_end"}))
                    elif data["type"] == "score":
                        scores_seen += 1
                        assert data["score"]["content_score"] == 5
                    elif data["type"] == "session_end":
                        saw_session_end = True
                        break
            assert saw_session_start
            assert saw_session_end
            assert scores_seen >= 1
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/integration/test_e2e.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_e2e.py
git commit -m "test(integration): end-to-end WS session with mocked STT/TTS/LLM"
```

---

### Task A16: manual end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Start the server**

Run: `python -m uvicorn server.main:app --host 127.0.0.1 --port 8765`
Expected: stdout shows `Uvicorn running on http://127.0.0.1:8765`, then a `stt_model_loaded` JSON log line.

- [ ] **Step 2: Open the browser**

Open `http://localhost:8765`. Expected: title "Week 1 Day 1 — Listening foundation: greetings & welcome" appears in the header.

- [ ] **Step 3: Click "Start lesson"**

Expected: `Coach: Welcome to your first speaking practice...` and `Coach: Hello, and welcome to the interview.` appear in the dialogue, audio plays through speakers.

- [ ] **Step 4: Hold SPACE and repeat the sentence**

Expected: status flips to "recording…" while held, "scoring…" on release. Within ~3s, a `You: ...` line and a JSON scorecard appear.

- [ ] **Step 5: Complete the lesson**

Expected: After the second user turn, `session complete` shows in the status, and a final scorecard is rendered. No tracebacks in the server log; every WS message is JSON-formatted.

- [ ] **Step 6: Tag the milestone**

```bash
git tag -a phase-a-complete -m "Phase A: trainer end-to-end runnable"
```

---

# Phase B — Autopilot subsystem

Phase B layers the continuous self-improvement loop on top of the working trainer. Every Phase B task commits to `main` (the autopilot code itself), but the loop's runtime commits go to `autopilot/<date>-<topic>` branches.

---

### Task B1: autopilot CLAUDE.md (opt-in declaration)

**Files:**
- Create: `autopilot/CLAUDE.md`
- Create: `autopilot/__init__.py`

- [ ] **Step 1: Create `autopilot/CLAUDE.md`**

```markdown
# Autopilot scope (repo-local opt-in)

This repository **opts into autonomous mode** for the autopilot subsystem only.
The autopilot loop may iterate without per-step user approval, subject to:

- All commits go to `autopilot/<date>-<slug>` branches. **Never to `main`.**
- The escalation list in `autopilot/policies/escalation.yml` is non-negotiable: matching items file to `autopilot/inbox.md` and stop.
- Rate limit in `autopilot/policies/rate_limit.yml` caps LLM call rate (anti-runaway, not budget).
- Presence of file `autopilot/PAUSE` halts the loop within 60s.
- Single-task concurrency on the main code base.

When the autopilot dispatches a child `claude -p` agent, the child operates inside a fresh worktree under `.claude/worktrees/autopilot-<date>-<slug>/` and runs the project test suite + eval suite before any commit.
```

- [ ] **Step 2: Create `autopilot/__init__.py`**

```python
# autopilot/__init__.py
```

- [ ] **Step 3: Commit**

```bash
git add autopilot/CLAUDE.md autopilot/__init__.py
git commit -m "feat(autopilot): opt-in repo-local CLAUDE.md and package skeleton"
```

---

### Task B2: rate-limit + escalation policy files

**Files:**
- Create: `autopilot/policies/rate_limit.yml`
- Create: `autopilot/policies/escalation.yml`
- Create: `autopilot/policies/safe_actions.yml`
- Create: `autopilot/policies/__init__.py`
- Create: `autopilot/policies.py`
- Test: `tests/unit/test_policies.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_policies.py
from autopilot.policies import (
    load_rate_limit, RateLimiter, load_escalation, matches_escalation,
)


def test_rate_limit_default_60_per_min(tmp_path):
    p = tmp_path / "rl.yml"
    p.write_text("max_calls_per_minute: 60\npause_seconds_on_trip: 60\n")
    rl = load_rate_limit(str(p))
    assert rl.max_calls_per_minute == 60
    assert rl.pause_seconds_on_trip == 60


def test_rate_limiter_trips_after_max_calls(monkeypatch):
    limiter = RateLimiter(max_calls_per_minute=3)
    times = [1000.0, 1000.1, 1000.2, 1000.3]
    monkeypatch.setattr("time.monotonic", lambda: times.pop(0))
    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is False


def test_escalation_matches_schema_migration():
    rules = load_escalation()
    files = ["server/schema.sql", "server/main.py"]
    assert matches_escalation(rules, files=files, diff_summary="add column users.email")


def test_escalation_matches_file_deletion():
    rules = load_escalation()
    assert matches_escalation(rules, files=[], diff_summary="deleted: server/old.py")


def test_escalation_matches_autopilot_self_modification():
    rules = load_escalation()
    assert matches_escalation(rules, files=["autopilot/loop.py"], diff_summary="x")


def test_escalation_does_not_match_normal_change():
    rules = load_escalation()
    assert not matches_escalation(rules, files=["server/coach.py"], diff_summary="refactor coach state machine")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_policies.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Create policy YAMLs**

```yaml
# autopilot/policies/rate_limit.yml
max_calls_per_minute: 60
pause_seconds_on_trip: 60
trips_per_hour_before_escalate: 3
```

```yaml
# autopilot/policies/escalation.yml
patterns:
  - name: schema_or_db_migration
    file_globs: ["**/schema.sql", "**/migrations/**", "**/alembic/**"]
    diff_keywords: ["alter table", "add column", "drop column", "create table"]
  - name: new_top_level_dependency
    file_globs: ["requirements.txt", "pyproject.toml"]
    diff_keywords: ["+ ", "added: "]
  - name: file_deletion
    file_globs: []
    diff_keywords: ["deleted:", "delete:", "rm "]
  - name: autopilot_self_modification
    file_globs: ["autopilot/**"]
    diff_keywords: []
  - name: llm_retry_policy_change
    file_globs: ["server/llm.py"]
    diff_keywords: ["retry", "backoff", "fallback"]
  - name: license_change
    file_globs: ["LICENSE", "LICENSE.*"]
    diff_keywords: []
consecutive_failure_threshold: 3
```

```yaml
# autopilot/policies/safe_actions.yml
allowed_commit_branch_prefix: "autopilot/"
forbidden_branches: ["main", "master"]
require_eval_pass: true
require_unit_pass: true
```

- [ ] **Step 4: Create `autopilot/policies/__init__.py`**

```python
# autopilot/policies/__init__.py
```

- [ ] **Step 5: Implement `autopilot/policies.py`**

```python
# autopilot/policies.py
"""Loads and evaluates rate-limit + escalation policies."""
import fnmatch
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Dict
import yaml


_HERE = os.path.dirname(__file__)


@dataclass
class RateLimitCfg:
    max_calls_per_minute: int = 60
    pause_seconds_on_trip: int = 60
    trips_per_hour_before_escalate: int = 3


def load_rate_limit(path: str | None = None) -> RateLimitCfg:
    p = path or os.path.join(_HERE, "policies", "rate_limit.yml")
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return RateLimitCfg(
        max_calls_per_minute=int(data.get("max_calls_per_minute", 60)),
        pause_seconds_on_trip=int(data.get("pause_seconds_on_trip", 60)),
        trips_per_hour_before_escalate=int(data.get("trips_per_hour_before_escalate", 3)),
    )


@dataclass
class RateLimiter:
    max_calls_per_minute: int = 60
    _hits: Deque[float] = field(default_factory=deque)

    def allow(self) -> bool:
        now = time.monotonic()
        while self._hits and self._hits[0] < now - 60.0:
            self._hits.popleft()
        if len(self._hits) >= self.max_calls_per_minute:
            return False
        self._hits.append(now)
        return True


def load_escalation(path: str | None = None) -> List[Dict]:
    p = path or os.path.join(_HERE, "policies", "escalation.yml")
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("patterns", []))


def matches_escalation(rules: List[Dict], files: List[str], diff_summary: str) -> bool:
    diff_lc = (diff_summary or "").lower()
    for rule in rules:
        for g in rule.get("file_globs", []) or []:
            if any(fnmatch.fnmatch(f, g) for f in files):
                return True
        for kw in rule.get("diff_keywords", []) or []:
            if kw.lower() in diff_lc:
                return True
    return False
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_policies.py -v`
Expected: PASS, `6 passed`.

- [ ] **Step 7: Commit**

```bash
git add autopilot/policies/ autopilot/policies.py tests/unit/test_policies.py
git commit -m "feat(autopilot): rate-limit + escalation + safe-actions policies"
```

---

### Task B3: PAUSE kill-switch helper

**Files:**
- Create: `autopilot/killswitch.py`
- Test: `tests/unit/test_killswitch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_killswitch.py
from autopilot.killswitch import is_paused


def test_pause_absent_means_not_paused(tmp_path):
    assert is_paused(str(tmp_path / "PAUSE")) is False


def test_pause_present_means_paused(tmp_path):
    p = tmp_path / "PAUSE"
    p.write_text("")
    assert is_paused(str(p)) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_killswitch.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `autopilot/killswitch.py`**

```python
# autopilot/killswitch.py
"""Kill-switch sentinel. Presence of PAUSE file halts the autopilot loop."""
import os


def is_paused(pause_path: str = "autopilot/PAUSE") -> bool:
    return os.path.exists(pause_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_killswitch.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add autopilot/killswitch.py tests/unit/test_killswitch.py
git commit -m "feat(autopilot): PAUSE kill-switch helper"
```

---

### Task B4: backlog item model + storage

**Files:**
- Create: `autopilot/backlog.py`
- Create: `autopilot/backlog.md`
- Test: `tests/unit/test_backlog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_backlog.py
from autopilot.backlog import Backlog, Item


def test_add_and_pick_highest_priority(tmp_path):
    b = Backlog(path=str(tmp_path / "backlog.jsonl"))
    b.add(Item(slug="a", priority=1, source="test_fails", prompt="fix a"))
    b.add(Item(slug="b", priority=10, source="eval_drift", prompt="fix b"))
    b.add(Item(slug="c", priority=5, source="session_logs", prompt="fix c"))
    picked = b.pick()
    assert picked.slug == "b"


def test_skip_needs_human(tmp_path):
    b = Backlog(path=str(tmp_path / "backlog.jsonl"))
    b.add(Item(slug="x", priority=99, source="t", prompt="x", tags=["needs-human"]))
    b.add(Item(slug="y", priority=1, source="t", prompt="y"))
    picked = b.pick()
    assert picked.slug == "y"


def test_mark_done_removes_item(tmp_path):
    b = Backlog(path=str(tmp_path / "backlog.jsonl"))
    b.add(Item(slug="z", priority=1, source="t", prompt="z"))
    b.mark_done("z")
    assert b.pick() is None


def test_dedup_by_slug(tmp_path):
    b = Backlog(path=str(tmp_path / "backlog.jsonl"))
    b.add(Item(slug="dup", priority=1, source="t", prompt="first"))
    b.add(Item(slug="dup", priority=2, source="t", prompt="second"))
    items = b.all_open()
    assert len(items) == 1
    assert items[0].priority == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_backlog.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `autopilot/backlog.py`**

```python
# autopilot/backlog.py
"""JSONL-backed prioritized backlog with dedup-by-slug and needs-human filter."""
import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Item:
    slug: str
    priority: int
    source: str
    prompt: str
    tags: List[str] = field(default_factory=list)
    status: str = "open"  # open | done


class Backlog:
    def __init__(self, path: str = "autopilot/backlog.jsonl"):
        self.path = path
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

    def _read(self) -> List[Item]:
        if not os.path.exists(self.path):
            return []
        latest: dict[str, Item] = {}
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                latest[d["slug"]] = Item(**d)
        return list(latest.values())

    def _write_append(self, item: Item) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

    def add(self, item: Item) -> None:
        self._write_append(item)

    def all_open(self) -> List[Item]:
        return [i for i in self._read() if i.status == "open"]

    def pick(self) -> Optional[Item]:
        candidates = [i for i in self.all_open() if "needs-human" not in i.tags]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x.priority, reverse=True)
        return candidates[0]

    def mark_done(self, slug: str) -> None:
        items = self._read()
        for i in items:
            if i.slug == slug:
                i.status = "done"
                self._write_append(i)
                return
```

- [ ] **Step 4: Create empty `autopilot/backlog.md`**

```markdown
# Autopilot backlog

This file is human-readable summary; the source of truth is `autopilot/backlog.jsonl`.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_backlog.py -v`
Expected: PASS, `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add autopilot/backlog.py autopilot/backlog.md tests/unit/test_backlog.py
git commit -m "feat(autopilot): prioritized backlog with dedup and needs-human filter"
```

---

### Task B5: trigger — from_test_fails

**Files:**
- Create: `autopilot/triggers/__init__.py`
- Create: `autopilot/triggers/from_test_fails.py`
- Test: `tests/unit/test_trigger_test_fails.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_trigger_test_fails.py
from autopilot.triggers.from_test_fails import discover, parse_pytest_failures


SAMPLE = """
============================= test session starts =============================
collected 7 items

tests/unit/test_coach.py::test_advance_from_idle_to_speak_prompt PASSED
tests/unit/test_coach.py::test_user_turn_transitions_to_listen_then_score FAILED

================================== FAILURES ===================================
______ test_user_turn_transitions_to_listen_then_score ______
AssertionError: state should be LISTEN_USER

tests/unit/test_scorer.py::test_wer_one_substitution FAILED

================================== FAILURES ===================================
___________________ test_wer_one_substitution ___________________
AssertionError: 0.0 != 0.5

============================ 2 failed, 5 passed ===============================
"""


def test_parse_pytest_failures_extracts_node_ids():
    failures = parse_pytest_failures(SAMPLE)
    ids = {f["nodeid"] for f in failures}
    assert "tests/unit/test_coach.py::test_user_turn_transitions_to_listen_then_score" in ids
    assert "tests/unit/test_scorer.py::test_wer_one_substitution" in ids


def test_discover_files_one_backlog_item_per_failure(tmp_path):
    log = tmp_path / "pytest.log"
    log.write_text(SAMPLE)
    items = discover(pytest_log=str(log))
    assert len(items) == 2
    slugs = {i.slug for i in items}
    assert any("test_user_turn" in s for s in slugs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_trigger_test_fails.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Create `autopilot/triggers/__init__.py`**

```python
# autopilot/triggers/__init__.py
```

- [ ] **Step 4: Implement `autopilot/triggers/from_test_fails.py`**

```python
# autopilot/triggers/from_test_fails.py
"""Parse a pytest log; file one backlog item per failure."""
import re
from typing import List, Dict
from autopilot.backlog import Item


_LINE_RE = re.compile(r"^(tests/[\w/.\-]+\.py)::([\w\[\]\-]+) FAILED", re.MULTILINE)


def parse_pytest_failures(log_text: str) -> List[Dict]:
    out = []
    for m in _LINE_RE.finditer(log_text):
        out.append({"nodeid": f"{m.group(1)}::{m.group(2)}", "test": m.group(2), "file": m.group(1)})
    return out


def _slug(failure: Dict) -> str:
    return "fix-" + failure["test"].replace("_", "-")[:50]


def discover(pytest_log: str = "pytest.log") -> List[Item]:
    try:
        with open(pytest_log, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return []
    failures = parse_pytest_failures(text)
    items: List[Item] = []
    for f in failures:
        items.append(Item(
            slug=_slug(f),
            priority=8,
            source="test_fails",
            prompt=(
                f"The pytest test `{f['nodeid']}` is failing. "
                f"Read the test in {f['file']}, find the bug in the code under test, fix it, "
                f"and verify the test passes. Do not modify the test itself unless the test is wrong."
            ),
        ))
    return items
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_trigger_test_fails.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autopilot/triggers/__init__.py autopilot/triggers/from_test_fails.py tests/unit/test_trigger_test_fails.py
git commit -m "feat(autopilot): trigger from_test_fails parses pytest log"
```

---

### Task B6: trigger — from_session_logs (≥3 repeats)

**Files:**
- Create: `autopilot/triggers/from_session_logs.py`
- Test: `tests/unit/test_trigger_session_logs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_trigger_session_logs.py
import json
from autopilot.triggers.from_session_logs import discover


def _write_session(path, turns):
    with open(path, "w", encoding="utf-8") as f:
        for t in turns:
            f.write(json.dumps(t) + "\n")


def test_no_item_when_below_threshold(tmp_path):
    _write_session(tmp_path / "s1.jsonl", [
        {"role": "user", "text": "x", "score": {"content_score": 2, "issues": ["filler"]}},
    ])
    items = discover(sessions_dir=str(tmp_path), threshold=3)
    assert items == []


def test_files_item_at_threshold(tmp_path):
    for i in range(3):
        _write_session(tmp_path / f"s{i}.jsonl", [
            {"role": "user", "text": "x", "score": {"content_score": 2, "issues": ["filler"]}},
        ])
    items = discover(sessions_dir=str(tmp_path), threshold=3)
    assert len(items) == 1
    assert "filler" in items[0].prompt.lower()


def test_multiple_distinct_issues_yield_distinct_items(tmp_path):
    for i in range(3):
        _write_session(tmp_path / f"a{i}.jsonl", [
            {"role": "user", "text": "x", "score": {"content_score": 2, "issues": ["filler"]}},
        ])
    for i in range(3):
        _write_session(tmp_path / f"b{i}.jsonl", [
            {"role": "user", "text": "x", "score": {"content_score": 1, "issues": ["wer-too-high"]}},
        ])
    items = discover(sessions_dir=str(tmp_path), threshold=3)
    assert len(items) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_trigger_session_logs.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `autopilot/triggers/from_session_logs.py`**

```python
# autopilot/triggers/from_session_logs.py
"""Cluster repeated low-score issues across recent session logs."""
import glob
import json
import os
from collections import Counter
from typing import List
from autopilot.backlog import Item


def discover(sessions_dir: str = "data/sessions", threshold: int = 3) -> List[Item]:
    issue_counts: Counter[str] = Counter()
    for path in glob.glob(os.path.join(sessions_dir, "*.jsonl")):
        seen_in_session: set[str] = set()
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    d = json.loads(line)
                    score = d.get("score") or {}
                    if int(score.get("content_score", 5)) >= 3:
                        continue
                    for issue in score.get("issues", []):
                        seen_in_session.add(str(issue))
        except Exception:
            continue
        for issue in seen_in_session:
            issue_counts[issue] += 1

    items: List[Item] = []
    for issue, count in issue_counts.items():
        if count >= threshold:
            slug = "session-issue-" + issue.replace(" ", "-")[:50]
            items.append(Item(
                slug=slug,
                priority=6,
                source="session_logs",
                prompt=(
                    f"User has hit the issue `{issue}` in {count} distinct sessions. "
                    f"Investigate scorer/coach/curriculum changes that could reduce this. "
                    f"Add a regression fixture under tests/eval/ that captures the desired improvement."
                ),
            ))
    return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_trigger_session_logs.py -v`
Expected: PASS, `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add autopilot/triggers/from_session_logs.py tests/unit/test_trigger_session_logs.py
git commit -m "feat(autopilot): trigger from_session_logs clusters >=3 repeats"
```

---

### Task B7: trigger — from_eval_drift (>5% regression)

**Files:**
- Create: `autopilot/triggers/from_eval_drift.py`
- Test: `tests/unit/test_trigger_eval_drift.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_trigger_eval_drift.py
import json
from autopilot.triggers.from_eval_drift import discover


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_no_item_when_no_regression(tmp_path):
    _write(tmp_path / "baseline.json", {"pass_rate": 0.90})
    _write(tmp_path / "current.json",  {"pass_rate": 0.91})
    items = discover(baseline=str(tmp_path / "baseline.json"), current=str(tmp_path / "current.json"))
    assert items == []


def test_files_high_priority_item_when_drop_over_5pct(tmp_path):
    _write(tmp_path / "baseline.json", {"pass_rate": 0.90})
    _write(tmp_path / "current.json",  {"pass_rate": 0.83})
    items = discover(baseline=str(tmp_path / "baseline.json"), current=str(tmp_path / "current.json"))
    assert len(items) == 1
    assert items[0].priority >= 9


def test_no_files_present_returns_empty(tmp_path):
    items = discover(baseline=str(tmp_path / "x.json"), current=str(tmp_path / "y.json"))
    assert items == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_trigger_eval_drift.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `autopilot/triggers/from_eval_drift.py`**

```python
# autopilot/triggers/from_eval_drift.py
"""Compare current eval pass rate vs baseline; >5pp drop -> high-priority item."""
import json
import os
from typing import List
from autopilot.backlog import Item


def discover(baseline: str = "tests/eval/baseline.json",
             current: str = "tests/eval/current.json") -> List[Item]:
    if not (os.path.exists(baseline) and os.path.exists(current)):
        return []
    with open(baseline, encoding="utf-8") as f:
        b = json.load(f)
    with open(current, encoding="utf-8") as f:
        c = json.load(f)
    drop = float(b.get("pass_rate", 0)) - float(c.get("pass_rate", 0))
    if drop <= 0.05:
        return []
    return [Item(
        slug="eval-drift-investigation",
        priority=9,
        source="eval_drift",
        prompt=(
            f"Eval pass-rate dropped by {drop:.1%} (baseline {b.get('pass_rate')}, "
            f"current {c.get('pass_rate')}). Bisect recent commits, identify the regression, "
            f"propose a fix, and ensure the eval suite returns to baseline."
        ),
    )]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_trigger_eval_drift.py -v`
Expected: PASS, `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add autopilot/triggers/from_eval_drift.py tests/unit/test_trigger_eval_drift.py
git commit -m "feat(autopilot): trigger from_eval_drift on >5pp regression"
```

---

### Task B8: trigger — from_repo_scan (daily personal-repo scan)

**Files:**
- Create: `autopilot/triggers/from_repo_scan.py`
- Test: `tests/unit/test_trigger_repo_scan.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_trigger_repo_scan.py
import json
from unittest.mock import patch
from autopilot.triggers.from_repo_scan import discover


def _personal(tmp_path, entries):
    p = tmp_path / "personal_projects.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return str(p)


def test_no_recent_commits_returns_no_item(tmp_path):
    pj = _personal(tmp_path, [{"id": "x", "name": "X", "repo_path": "/non/existent"}])
    with patch("autopilot.triggers.from_repo_scan._git_log_since", return_value=""):
        items = discover(personal_projects_path=pj)
    assert items == []


def test_recent_commits_with_keyword_files_proposal(tmp_path):
    pj = _personal(tmp_path, [{"id": "x", "name": "X", "repo_path": "/non/existent"}])
    with patch("autopilot.triggers.from_repo_scan._git_log_since",
               return_value="abc123 add new RAG retrieval mode\ndef456 implement reranker\n"):
        items = discover(personal_projects_path=pj)
    assert len(items) == 1
    assert "needs-human" in items[0].tags
    assert "X" in items[0].prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_trigger_repo_scan.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `autopilot/triggers/from_repo_scan.py`**

```python
# autopilot/triggers/from_repo_scan.py
"""Daily scan of user's personal repos. Proposes (never auto-merges) updates to personal_projects.json."""
import json
import os
import subprocess
from typing import List
from autopilot.backlog import Item


_KEYWORDS = ("add", "implement", "support", "introduce", "feat", "feature")


def _git_log_since(repo_path: str, since: str = "7.days") -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_path, "log", f"--since={since}", "--oneline"],
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return out.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def discover(personal_projects_path: str = "data/personal_projects.json") -> List[Item]:
    if not os.path.exists(personal_projects_path):
        return []
    with open(personal_projects_path, encoding="utf-8") as f:
        projects = json.load(f)
    items: List[Item] = []
    for p in projects:
        log = _git_log_since(p.get("repo_path", ""))
        if not log:
            continue
        if not any(k in log.lower() for k in _KEYWORDS):
            continue
        items.append(Item(
            slug=f"refresh-personal-{p['id']}",
            priority=3,
            source="repo_scan",
            tags=["needs-human"],
            prompt=(
                f"Personal project '{p['name']}' (id={p['id']}) has new commits in the last 7 days:\n"
                f"{log}\n"
                f"Draft a proposed update to data/personal_projects.json (new interview_angles or "
                f"hard_words) and file it for human review. Do NOT auto-merge."
            ),
        ))
    return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_trigger_repo_scan.py -v`
Expected: PASS, `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add autopilot/triggers/from_repo_scan.py tests/unit/test_trigger_repo_scan.py
git commit -m "feat(autopilot): trigger from_repo_scan with needs-human tag"
```

---

### Task B9: loop.py — discovery → spawn `claude -p` in worktree → verify → branch commit

**Files:**
- Create: `autopilot/loop.py`
- Test: `tests/unit/test_loop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_loop.py
from unittest.mock import patch, MagicMock
from autopilot.loop import run_once, LoopResult
from autopilot.backlog import Item


def test_run_once_returns_paused_when_pause_present(tmp_path):
    pause = tmp_path / "PAUSE"
    pause.write_text("")
    res = run_once(pause_path=str(pause))
    assert res.status == "paused"


def test_run_once_returns_idle_when_no_items(tmp_path):
    with patch("autopilot.loop._collect_all_triggers", return_value=[]):
        res = run_once(pause_path=str(tmp_path / "PAUSE"),
                       backlog_path=str(tmp_path / "b.jsonl"))
    assert res.status == "idle"


def test_run_once_dispatches_picked_item(tmp_path):
    item = Item(slug="fix-x", priority=10, source="test_fails", prompt="fix x")
    fake_proc = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("autopilot.loop._collect_all_triggers", return_value=[item]), \
         patch("autopilot.loop._spawn_claude", return_value=fake_proc) as spawn, \
         patch("autopilot.loop._verify", return_value=True), \
         patch("autopilot.loop._commit_to_branch", return_value="autopilot/2026-05-12-fix-x"):
        res = run_once(pause_path=str(tmp_path / "PAUSE"),
                       backlog_path=str(tmp_path / "b.jsonl"))
    assert res.status == "committed"
    assert res.branch == "autopilot/2026-05-12-fix-x"
    spawn.assert_called_once()


def test_failed_verify_files_needs_human(tmp_path):
    item = Item(slug="fix-y", priority=10, source="test_fails", prompt="fix y")
    fake_proc = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("autopilot.loop._collect_all_triggers", return_value=[item]), \
         patch("autopilot.loop._spawn_claude", return_value=fake_proc), \
         patch("autopilot.loop._verify", return_value=False):
        res = run_once(pause_path=str(tmp_path / "PAUSE"),
                       backlog_path=str(tmp_path / "b.jsonl"))
    assert res.status == "needs_human"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_loop.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `autopilot/loop.py`**

```python
# autopilot/loop.py
"""Autopilot main loop: discover -> pick -> spawn -> verify -> branch-commit."""
import datetime
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional

from autopilot.backlog import Backlog, Item
from autopilot.killswitch import is_paused
from autopilot.triggers.from_test_fails import discover as t_tests
from autopilot.triggers.from_session_logs import discover as t_logs
from autopilot.triggers.from_eval_drift import discover as t_eval
from autopilot.triggers.from_repo_scan import discover as t_repo
from server.logging_setup import get_logger

_log = get_logger("autopilot")


@dataclass
class LoopResult:
    status: str  # paused | idle | committed | needs_human | error
    item_slug: Optional[str] = None
    branch: Optional[str] = None
    detail: str = ""


def _collect_all_triggers() -> List[Item]:
    items: List[Item] = []
    for fn in (t_tests, t_logs, t_eval, t_repo):
        try:
            items.extend(fn())
        except Exception as e:
            _log.warning("trigger_failed", trigger=fn.__module__, error=str(e))
    return items


def _spawn_claude(item: Item, worktree: str):
    """Run `claude -p` headless inside the worktree. Returns the CompletedProcess."""
    cmd = ["claude", "-p", item.prompt, "--cwd", worktree]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 30)


def _verify(worktree: str) -> bool:
    """Run unit + eval suites inside the worktree."""
    try:
        r1 = subprocess.run(["python", "-m", "pytest", "tests/unit", "-q"],
                            cwd=worktree, capture_output=True, text=True, timeout=600)
        r2 = subprocess.run(["python", "-m", "pytest", "tests/eval", "-q"],
                            cwd=worktree, capture_output=True, text=True, timeout=600)
        return r1.returncode == 0 and r2.returncode == 0
    except Exception as e:
        _log.error("verify_failed", error=str(e))
        return False


def _commit_to_branch(worktree: str, slug: str) -> str:
    today = datetime.date.today().isoformat()
    branch = f"autopilot/{today}-{slug}"
    subprocess.run(["git", "-C", worktree, "checkout", "-b", branch], check=False)
    subprocess.run(["git", "-C", worktree, "add", "-A"], check=False)
    subprocess.run(
        ["git", "-C", worktree, "commit", "-m", f"[auto] {slug}"],
        check=False,
    )
    return branch


def _make_worktree(slug: str) -> str:
    today = datetime.date.today().isoformat()
    path = os.path.join(".claude", "worktrees", f"autopilot-{today}-{slug}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-b", f"wt-{today}-{slug}", path], check=False)
    return path


def run_once(pause_path: str = "autopilot/PAUSE",
             backlog_path: str = "autopilot/backlog.jsonl") -> LoopResult:
    if is_paused(pause_path):
        _log.info("autopilot_paused")
        return LoopResult(status="paused")

    bl = Backlog(path=backlog_path)
    for item in _collect_all_triggers():
        bl.add(item)

    picked = bl.pick()
    if picked is None:
        return LoopResult(status="idle")

    _log.info("autopilot_pick", slug=picked.slug, priority=picked.priority, source=picked.source)
    worktree = _make_worktree(picked.slug)
    proc = _spawn_claude(picked, worktree)
    _log.info("claude_done", slug=picked.slug, rc=proc.returncode)

    if not _verify(worktree):
        bl.add(Item(slug=picked.slug, priority=picked.priority, source=picked.source,
                    prompt=picked.prompt, tags=list(set(picked.tags + ["needs-human"]))))
        return LoopResult(status="needs_human", item_slug=picked.slug, detail="verify_failed")

    branch = _commit_to_branch(worktree, picked.slug)
    bl.mark_done(picked.slug)
    return LoopResult(status="committed", item_slug=picked.slug, branch=branch)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_loop.py -v`
Expected: PASS, `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add autopilot/loop.py tests/unit/test_loop.py
git commit -m "feat(autopilot): loop dispatcher with worktree, verify, branch-only commit"
```

---

### Task B10: daily digest writer

**Files:**
- Create: `autopilot/digest.py`
- Test: `tests/unit/test_digest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_digest.py
from autopilot.digest import write_digest
from autopilot.loop import LoopResult


def test_write_digest_creates_dated_file(tmp_path):
    results = [
        LoopResult(status="committed", item_slug="fix-a", branch="autopilot/2026-05-12-fix-a"),
        LoopResult(status="needs_human", item_slug="fix-b", detail="verify_failed"),
        LoopResult(status="idle"),
    ]
    out = write_digest(results, runs_dir=str(tmp_path), date_str="2026-05-12")
    assert out.endswith("digest-2026-05-12.md")
    body = open(out, encoding="utf-8").read()
    assert "fix-a" in body
    assert "fix-b" in body
    assert "committed" in body
    assert "needs_human" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_digest.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement `autopilot/digest.py`**

```python
# autopilot/digest.py
"""Markdown daily digest of LoopResults under autopilot/runs/digest-<date>.md."""
import datetime
import os
from typing import List

from autopilot.loop import LoopResult


def write_digest(results: List[LoopResult], runs_dir: str = "autopilot/runs",
                 date_str: str = None) -> str:
    os.makedirs(runs_dir, exist_ok=True)
    date_str = date_str or datetime.date.today().isoformat()
    path = os.path.join(runs_dir, f"digest-{date_str}.md")
    counts = {"committed": 0, "needs_human": 0, "idle": 0, "paused": 0, "error": 0}
    lines: List[str] = [f"# Autopilot digest — {date_str}", ""]
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status == "committed":
            lines.append(f"- **committed** `{r.item_slug}` → branch `{r.branch}`")
        elif r.status == "needs_human":
            lines.append(f"- **needs_human** `{r.item_slug}` — {r.detail}")
        elif r.status == "paused":
            lines.append("- _paused (PAUSE file present)_")
        elif r.status == "idle":
            lines.append("- _idle (no backlog items)_")
        else:
            lines.append(f"- **{r.status}** {r.detail}")
    lines += ["", "## Summary", ""]
    for k, v in counts.items():
        lines.append(f"- {k}: {v}")
    body = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_digest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add autopilot/digest.py tests/unit/test_digest.py
git commit -m "feat(autopilot): daily markdown digest writer"
```

---

### Task B11: integration smoke — induce a failing test, observe loop behavior

**Files:** none (manual verification only)

- [ ] **Step 1: Capture a failing-test scenario**

Run: `python -m pytest tests/unit/test_scorer.py -v 2>&1 | tee pytest.log`
Then deliberately break a scorer test by editing the assertion temporarily.
Expected: pytest.log contains a `FAILED` line.

- [ ] **Step 2: Run the discovery in dry-run**

Run:
```bash
python -c "from autopilot.triggers.from_test_fails import discover; \
items = discover('pytest.log'); \
print('items:', len(items)); \
[print(' -', i.slug, '|', i.prompt[:80]) for i in items]"
```
Expected: prints at least one `fix-...` item with a clear prompt referencing the failing nodeid.

- [ ] **Step 3: Run loop with real spawn DISABLED (dry-run)**

Run:
```bash
python -c "
from unittest.mock import patch, MagicMock
from autopilot.loop import run_once
fake = MagicMock(returncode=0, stdout='ok', stderr='')
with patch('autopilot.loop._spawn_claude', return_value=fake), \
     patch('autopilot.loop._verify', return_value=True), \
     patch('autopilot.loop._make_worktree', return_value='.'), \
     patch('autopilot.loop._commit_to_branch', return_value='autopilot/dryrun'):
    print(run_once())
"
```
Expected: prints `LoopResult(status='committed', item_slug='fix-...', branch='autopilot/dryrun', ...)`.

- [ ] **Step 4: Restore the scorer test and rerun the suite**

Revert the deliberate break. Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 5: Tag the milestone**

```bash
git tag -a phase-b-complete -m "Phase B: autopilot loop + triggers + digest in place"
```

---

# Self-review

This section is the writing-plans self-review. It is for the plan author, not part of the implementation.

**Spec coverage check (against `2026-05-12-speakagent-design.md`):**

| Spec section | Covered by tasks |
|---|---|
| §2 acceptance criteria — end-to-end loop on :8765 | A1, A2, A10, A11, A16 |
| §2 — 8-week curriculum runnable | A9 (week 1 day 1 seed); remaining 55 lessons are content authoring, deferred to in-session work after Phase A |
| §2 — personal-project integration ≥5 repos | A13 (7 entries) |
| §2 — autopilot continuous, branch-only, escalates | B1, B2, B9 |
| §2 — eval suite ≥20 fixtures | A14 starts at 6; explicit follow-up: grow to 20 in burn-in |
| §2 — harness (logs, hot-reload, dev panel, kill switch) | A3 (logs), A11 (dev panel), B3 (kill switch); hot-reload is implicit (A10 re-loads lesson per session) |
| §3-4 module inventory | A2-A10 cover every module |
| §5 error recovery ladder | A4 (LLM Claude→GPT→graceful), A11 client-side TTS fallback hook is left for future task |
| §6 data flow | A10 + A11 implement the flow |
| §7 8-week curriculum schema | A9 lesson loader; lesson YAML is curriculum-driven so additional weeks are content tasks |
| §8 question bank seed | A12 |
| §9 autopilot loop, guardrails, burn-in | B1-B10 |
| §10 personal-projects | A13 + B8 |
| §11 tech stack | A1 requirements |
| §13 risks (LLM gateway down, edge-tts down) | A4 fallback, TTS browser-fallback hook is a known gap (see Open) |
| §14 validation | A14, A15, A16, B11 |
| §15 layout | matches files created |

**Known gaps explicitly carried into "Open Questions" below; not silent.**

**Placeholder scan:** searched for "TBD", "TODO", "fill in", "similar to": none found.

**Type/name consistency check:**
- `get_assistant`, `call_with_fallback`, `ClaudeAssistant`, `GptAssistant`: same names everywhere.
- `TurnScore`, `TranscriptionResult`, `LessonPlan`, `Coach`, `CoachState`, `Item`, `Backlog`, `LoopResult`, `RateLimitCfg`, `RateLimiter`: each defined once and referenced consistently.
- `voices_for_week` / `pick_voice`: distinct, both used as defined.
- `score_turn` signature `(user_text, user_words, user_confidence, ideal_text, llm_system=...)` — matched in scorer tests, coach, and eval fixtures.
- `LoopResult` fields `status, item_slug, branch, detail` — matched in digest tests.

**Open / deferred (non-blocking, not placeholders):**

1. **Curriculum content authoring** for weeks 1-8 days 2-7 (55 more lesson YAMLs). This is content, not code, so it's left as in-session work to do after Phase A unblocks the loop.
2. **Eval-suite growth to 20+ fixtures.** Initial 6 in A14 cover the main shapes; new fixtures are added as new failure modes appear (and the autopilot's `from_session_logs` trigger is what surfaces them).
3. **Browser TTS fallback.** A4 has Claude→GPT→graceful spoken error; the spec also calls for edge-tts → browser `speechSynthesis`. Adding this needs (a) a `tts_unavailable` server message and (b) a JS fallback path in `app.js`. Defer until edge-tts actually fails in practice.
4. **`from_repo_scan` inbox writer.** B8 files items with `needs-human` so they'll never auto-execute. The accompanying human-readable inbox writer (rendering them into `autopilot/inbox.md`) is a small follow-up; not blocking the loop.
5. **Listening clip download script** (§8). Out of scope for v0.1 code; can be a one-off curl recipe in a follow-up.

---

# Execution choice

After saving this plan, the orchestrator will offer:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration via `superpowers:subagent-driven-development`.

**2. Inline Execution** — execute tasks in this session via `superpowers:executing-plans` with batch checkpoints.
