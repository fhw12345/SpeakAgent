"""Unit tests for VadSegmenter using a stub detector so silero-vad/onnxruntime
is not required at test time. Stub returns 1.0 for "speech" frames and 0.0
for "silence" frames based on the magnitude of the first sample of each
512-sample window."""
import numpy as np

from server.vad import VadSegmenter


def _frames(values, n_frames):
    """Generate `n_frames` 512-sample int16 frames; each frame is filled
    entirely with `values[i]` so the stub detector can classify by magnitude."""
    out = bytearray()
    for v in values[:n_frames]:
        out.extend(np.full(512, v, dtype=np.int16).tobytes())
    return bytes(out)


def _stub_detector(frame):
    # frame is float32 in [-1, 1]; magnitude > 0.1 → speech
    return 1.0 if float(np.max(np.abs(frame))) > 0.1 else 0.0


def _seg(**kwargs):
    return VadSegmenter(detector=_stub_detector, **kwargs)


def test_vad_emits_start_on_speech_frames():
    seg = _seg(min_speech_ms=64)  # 2 frames of 32ms each
    events = seg.process_frame(_frames([20000] * 4, 4))
    assert "start" in events


def test_vad_emits_end_after_silence():
    seg = _seg(min_speech_ms=64, min_silence_ms=128)
    events = []
    events.extend(seg.process_frame(_frames([20000] * 5, 5)))
    events.extend(seg.process_frame(_frames([0] * 8, 8)))
    assert events.count("start") == 1
    assert events.count("end") == 1
    assert events.index("start") < events.index("end")


def test_vad_ignores_short_blip():
    seg = _seg(min_speech_ms=200)  # ~7 frames @ 32ms
    # 1 speech frame then silence — should be dropped, no start emitted.
    events = []
    events.extend(seg.process_frame(_frames([20000], 1)))
    events.extend(seg.process_frame(_frames([0] * 10, 10)))
    assert "start" not in events
    assert "end" not in events


def test_reset_clears_state():
    seg = _seg(min_speech_ms=64, min_silence_ms=128)
    seg.process_frame(_frames([20000] * 5, 5))
    seg.reset()
    # After reset, a fresh sequence should re-emit a start.
    events = seg.process_frame(_frames([20000] * 5, 5))
    assert "start" in events
