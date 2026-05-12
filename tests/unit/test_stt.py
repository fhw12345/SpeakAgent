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
