"""Unit tests for VadSegmenter.

We stub the silero model with a deterministic fake that returns a fixed
probability based on input energy. This makes the state-machine tests
fully deterministic and removes the dependency on silero's quirks for
synthetic inputs (e.g., pure sines vs. real speech).
"""
import numpy as np
import pytest

from server import vad as vad_mod
from server.vad import VadSegmenter, FRAME_BYTES, FRAME_MS, load_model_once


class FakeModel:
    """Returns 0.9 for non-zero input, 0.1 for silent input."""

    def __init__(self):
        self.reset_calls = 0

    def __call__(self, tensor, sample_rate):
        arr = tensor.numpy() if hasattr(tensor, "numpy") else np.asarray(tensor)
        return 0.9 if float(np.abs(arr).mean()) > 1e-4 else 0.1

    def reset_states(self):
        self.reset_calls += 1


def _speech_frame() -> bytes:
    rng = np.random.default_rng(42)
    arr = (rng.normal(0, 0.3, size=512) * 32767).astype(np.int16)
    return arr.tobytes()


def _silence_frame() -> bytes:
    return np.zeros(512, dtype=np.int16).tobytes()


@pytest.fixture
def fake_model(monkeypatch):
    fm = FakeModel()
    monkeypatch.setattr(vad_mod, "_MODEL", fm)
    return fm


def test_vad_emits_start_on_speech_frames(fake_model):
    seg = VadSegmenter(min_speech_ms=200, min_silence_ms=400)
    events_total = []
    # 8 frames * 32ms = 256ms -> should cross 200ms threshold
    for i in range(8):
        events_total.extend(seg.process_frame(_speech_frame()))
    assert "start" in events_total
    # Only one start
    assert events_total.count("start") == 1


def test_vad_emits_end_after_silence(fake_model):
    seg = VadSegmenter(min_speech_ms=200, min_silence_ms=400)
    # speech until in_speech
    for _ in range(8):
        seg.process_frame(_speech_frame())
    assert seg.in_speech
    events = []
    for _ in range(16):  # 16 * 32ms = 512ms, exceeds 400ms silence threshold
        events.extend(seg.process_frame(_silence_frame()))
    assert "end" in events
    assert events.count("end") == 1


def test_vad_ignores_short_blip(fake_model):
    seg = VadSegmenter(min_speech_ms=200, min_silence_ms=400)
    events = []
    # 5 frames * 32ms = 160ms, less than 200ms min_speech_ms
    for _ in range(5):
        events.extend(seg.process_frame(_speech_frame()))
    # then silence cancels
    for _ in range(5):
        events.extend(seg.process_frame(_silence_frame()))
    assert "start" not in events


def test_reset_clears_state(fake_model):
    seg = VadSegmenter(min_speech_ms=200, min_silence_ms=400)
    for _ in range(8):
        seg.process_frame(_speech_frame())
    assert seg.in_speech
    seg.reset()
    assert seg.in_speech is False
    events = []
    for _ in range(16):
        events.extend(seg.process_frame(_silence_frame()))
    assert "end" not in events


def test_singleton_load(monkeypatch):
    # Force a reload of the singleton with a real (cached) model
    monkeypatch.setattr(vad_mod, "_MODEL", None)
    a = load_model_once()
    b = load_model_once()
    assert a is b


def test_process_frame_rejects_wrong_size(fake_model):
    seg = VadSegmenter()
    with pytest.raises(ValueError):
        seg.process_frame(b"\x00" * (FRAME_BYTES - 2))


def test_frame_constants():
    assert FRAME_BYTES == 1024
    assert FRAME_MS == 32
