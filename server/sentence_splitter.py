"""Incremental sentence accumulator for streaming LLM output.

Splits on `.`, `!`, `?`, or newline. A completed sentence must be at
least 4 characters long (after strip). For `.` specifically we also
reject the boundary when it sits inside a decimal number (digit-dot-digit
like ``3.14``), so ``Pi is 3.14 exactly.`` stays one sentence.
"""
from __future__ import annotations

_TERMINATORS = ".!?\n"
_MIN_SENTENCE_LEN = 4


class SentenceAccumulator:
    def __init__(self) -> None:
        self._buf: str = ""

    def push(self, delta: str) -> list[str]:
        if not delta:
            return []
        self._buf += delta
        out: list[str] = []
        start = 0
        i = 0
        while i < len(self._buf):
            ch = self._buf[i]
            if ch in _TERMINATORS:
                if ch == ".":
                    if i + 1 >= len(self._buf):
                        break
                    if self._is_decimal_dot(i):
                        i += 1
                        continue
                candidate = self._buf[start : i + 1].strip()
                if len(candidate) >= _MIN_SENTENCE_LEN:
                    out.append(candidate)
                    start = i + 1
            i += 1
        self._buf = self._buf[start:]
        return out

    def _is_decimal_dot(self, i: int) -> bool:
        prev_ch = self._buf[i - 1] if i > 0 else ""
        next_ch = self._buf[i + 1] if i + 1 < len(self._buf) else ""
        return prev_ch.isdigit() and next_ch.isdigit()

    def flush(self) -> list[str]:
        leftover = self._buf.strip()
        self._buf = ""
        if leftover and len(leftover) >= _MIN_SENTENCE_LEN:
            return [leftover]
        return []
