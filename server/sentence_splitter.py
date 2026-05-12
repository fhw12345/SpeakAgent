from __future__ import annotations

_HARD_TERMINATORS = "!?\n"
_SOFT_TERMINATOR = "."
_MIN_SENTENCE_LEN = 4


class SentenceAccumulator:
    def __init__(self) -> None:
        self._buf: str = ""

    def push(self, delta: str) -> list[str]:
        if not delta:
            return []
        self._buf += delta
        sentences: list[str] = []
        start = 0
        i = 0
        while i < len(self._buf):
            ch = self._buf[i]
            if ch == _SOFT_TERMINATOR:
                if i + 1 >= len(self._buf):
                    break
                if self._buf[i + 1].isalnum():
                    i += 1
                    continue
                end = i + 1
            elif ch in _HARD_TERMINATORS:
                end = i if ch == "\n" else i + 1
            else:
                i += 1
                continue

            candidate = self._buf[start:end].strip()
            token_len = (i + 1) - start
            if token_len >= _MIN_SENTENCE_LEN and candidate:
                sentences.append(candidate)
                i += 1
                while i < len(self._buf) and self._buf[i] in " \t":
                    i += 1
                start = i
            else:
                i += 1
        self._buf = self._buf[start:]
        return sentences

    def flush(self) -> list[str]:
        leftover = self._buf.strip()
        self._buf = ""
        return [leftover] if leftover else []
