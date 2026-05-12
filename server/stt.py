"""faster-whisper STT wrapper. Long-lived engine; one transcribe call per utterance."""
import math
import os
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
    def __init__(self, model_name: str = "small", device: str | None = None,
                 compute_type: str | None = None):
        device = device or os.environ.get("WHISPER_DEVICE", "cpu")
        compute_type = compute_type or os.environ.get(
            "WHISPER_COMPUTE_TYPE", "int8" if device == "cpu" else "auto"
        )
        _log.info("stt_loading_model", model=model_name, device=device, compute_type=compute_type)
        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
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
