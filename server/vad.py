"""silero-vad wrapper: streaming voice-activity detection with a state machine
that emits "start" / "end" events based on min_speech_ms / min_silence_ms.

silero-vad imports torchaudio at module load. torchaudio's compiled extension
fails to load on some Windows builds even though we never use the audio I/O
helpers. We pre-install a no-op torchaudio shim BEFORE the silero-vad import
so the ONNX path remains available. If silero-vad still cannot import, the
module exposes a stubbed load_model_once() that raises at first use; tests
patch _MODEL directly to keep the module importable in any environment.
"""
from __future__ import annotations

import sys
import threading
from typing import List, Literal, Optional

import numpy as np

from server.logging_setup import get_logger

_log = get_logger("vad")


def _install_torchaudio_shim() -> None:
    if "torchaudio" in sys.modules:
        return
    try:
        import torchaudio  # noqa: F401
        return
    except Exception:
        pass

    class _Shim:
        def __getattr__(self, name):
            raise ImportError(f"torchaudio shim: {name} not available")

    sys.modules["torchaudio"] = _Shim()


_install_torchaudio_shim()

try:
    from silero_vad import load_silero_vad  # type: ignore
    import torch  # type: ignore
except Exception as _import_err:  # pragma: no cover - exercised only when env lacks deps
    load_silero_vad = None  # type: ignore[assignment]
    torch = None  # type: ignore[assignment]
    _IMPORT_ERROR = _import_err
else:
    _IMPORT_ERROR = None


_MODEL = None
_MODEL_LOCK = threading.Lock()

FRAME_SAMPLES = 512  # silero requires exactly 512 samples @ 16 kHz
FRAME_BYTES = FRAME_SAMPLES * 2  # int16 LE
FRAME_MS = (FRAME_SAMPLES * 1000) // 16000  # = 32 ms


def load_model_once():
    """Return the singleton silero ONNX model. Loaded lazily, thread-safe."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        if load_silero_vad is None:
            raise RuntimeError(f"silero-vad not installed: {_IMPORT_ERROR!r}")
        _log.info("vad_model_loading")
        _MODEL = load_silero_vad(onnx=True)
        _log.info("vad_model_loaded")
    return _MODEL


VadEvent = Literal["start", "end"]


class VadSegmenter:
    """Streaming VAD segmenter. Feed 32-ms frames, get start/end events."""

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_silence_ms: int = 400,
        min_speech_ms: int = 200,
    ) -> None:
        if sample_rate != 16000:
            raise ValueError("VadSegmenter only supports 16 kHz")
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.min_silence_ms = min_silence_ms
        self.min_speech_ms = min_speech_ms
        self.in_speech = False
        self.speech_ms = 0
        self.silence_ms = 0
        self._model = load_model_once()

    def reset(self) -> None:
        self.in_speech = False
        self.speech_ms = 0
        self.silence_ms = 0
        if hasattr(self._model, "reset_states"):
            try:
                self._model.reset_states()
            except Exception:
                pass

    def process_frame(self, pcm_bytes: bytes) -> List[VadEvent]:
        if len(pcm_bytes) != FRAME_BYTES:
            raise ValueError(
                f"VadSegmenter expects exactly {FRAME_BYTES} bytes "
                f"({FRAME_SAMPLES} int16 samples), got {len(pcm_bytes)}"
            )
        arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        prob = self._infer(arr)
        events: List[VadEvent] = []
        if prob >= self.threshold:
            self.speech_ms += FRAME_MS
            self.silence_ms = 0
            if not self.in_speech and self.speech_ms >= self.min_speech_ms:
                self.in_speech = True
                events.append("start")
        else:
            self.silence_ms += FRAME_MS
            if not self.in_speech:
                # below threshold and not in speech: decay any pending speech
                self.speech_ms = 0
            if self.in_speech and self.silence_ms >= self.min_silence_ms:
                self.in_speech = False
                self.speech_ms = 0
                events.append("end")
        return events

    def _infer(self, arr: np.ndarray) -> float:
        if torch is None:  # pragma: no cover
            raise RuntimeError("torch not available for VAD inference")
        out = self._model(torch.from_numpy(arr), self.sample_rate)
        try:
            return float(out)
        except TypeError:
            return float(out.item())
