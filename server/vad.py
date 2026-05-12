"""Silero-VAD wrapper that turns a stream of 16 kHz int16 PCM frames into
discrete `start` / `end` segmentation events.

The class is intentionally injectable: callers may pass a custom
`detector` callable returning a per-frame speech probability. The default
loads silero-vad lazily so importing this module never triggers a model
download in test environments that don't need it.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, List, Literal, Optional

import numpy as np

VadEvent = Literal["start", "end"]

_FRAME_SAMPLES = 512  # silero-vad expects 512-sample frames at 16 kHz


@dataclass
class _State:
    in_speech: bool = False
    speech_ms: float = 0.0
    silence_ms: float = 0.0
    pending_start: bool = False  # speech detected but min_speech_ms not reached yet


def _silero_detector_factory() -> Callable[[np.ndarray], float]:
    """Lazily build a silero-vad detector. Imported on first call so the
    onnxruntime + model download only happens when VAD is actually used."""
    try:
        from silero_vad import load_silero_vad  # type: ignore
    except Exception as e:  # pragma: no cover - exercised when dep absent
        raise RuntimeError(f"silero_vad unavailable: {e}") from e

    model = load_silero_vad(onnx=True)

    def _detect(frame: np.ndarray) -> float:
        # silero-vad onnx accepts numpy float32 directly via its __call__.
        prob = model(frame.astype(np.float32), 16000)
        # Some builds return a torch.Tensor wrapper even with onnx=True.
        return float(prob.item() if hasattr(prob, "item") else prob)

    return _detect


class VadSegmenter:
    """Stream-oriented voice-activity segmenter.

    Feed `process_frame(pcm_bytes)` raw little-endian int16 mono PCM at
    `sample_rate`. Returns a list of events for that frame; typically
    empty, occasionally `["start"]` or `["end"]`.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_silence_ms: int = 400,
        min_speech_ms: int = 200,
        detector: Optional[Callable[[np.ndarray], float]] = None,
    ):
        if sample_rate != 16000:
            raise ValueError("VadSegmenter currently only supports 16 kHz")
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.min_silence_ms = min_silence_ms
        self.min_speech_ms = min_speech_ms
        self._detector = detector
        self._detector_lock = threading.Lock()
        self._state = _State()
        self._buf = bytearray()

    def _ensure_detector(self) -> Callable[[np.ndarray], float]:
        if self._detector is not None:
            return self._detector
        with self._detector_lock:
            if self._detector is None:
                self._detector = _silero_detector_factory()
        return self._detector

    def reset(self) -> None:
        self._state = _State()
        self._buf.clear()

    def process_frame(self, pcm_bytes: bytes) -> List[VadEvent]:
        if not pcm_bytes:
            return []
        self._buf.extend(pcm_bytes)
        events: List[VadEvent] = []
        frame_bytes = _FRAME_SAMPLES * 2
        detector = self._ensure_detector()
        frame_ms = (_FRAME_SAMPLES / self.sample_rate) * 1000.0
        while len(self._buf) >= frame_bytes:
            chunk = bytes(self._buf[:frame_bytes])
            del self._buf[:frame_bytes]
            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            prob = detector(samples)
            self._step(prob, frame_ms, events)
        return events

    def _step(self, prob: float, frame_ms: float, events: List[VadEvent]) -> None:
        is_speech = prob >= self.threshold
        st = self._state
        if is_speech:
            st.silence_ms = 0.0
            st.speech_ms += frame_ms
            if not st.in_speech and st.speech_ms >= self.min_speech_ms:
                st.in_speech = True
                events.append("start")
        else:
            if st.in_speech:
                st.silence_ms += frame_ms
                if st.silence_ms >= self.min_silence_ms:
                    st.in_speech = False
                    st.speech_ms = 0.0
                    st.silence_ms = 0.0
                    events.append("end")
            else:
                # speech below min_speech_ms followed by silence: blip → drop
                st.speech_ms = 0.0
                st.silence_ms = 0.0
