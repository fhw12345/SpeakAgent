"""Incremental sentence accumulator for streaming LLM deltas.

Splits on '.', '!', '?', or newline. A candidate sentence must be at least
4 characters of trimmed content to flush — this rejects "Mr." / "3.14"
style false positives while still emitting short replies like "Hi!".
"""
from __future__ import annotations

from typing import List

_TERMINATORS = set(".!?\n")
_MIN_LEN = 4


class SentenceAccumulator:
    def __init__(self) -> None:
        self._buf: str = ""

    def push(self, delta: str) -> List[str]:
        if not delta:
            return []
        self._buf += delta
        out: List[str] = []
        start = 0
        i = 0
        n = len(self._buf)
        while i < n:
            ch = self._buf[i]
            if ch in _TERMINATORS:
                # Skip "." inside numeric decimals (digit on both sides),
                # so "3.14" doesn't split. If the next char hasn't arrived
                # yet (period at end of buffer after a digit), defer the
                # split until more input arrives.
                if ch == "." and i > 0 and self._buf[i - 1].isdigit():
                    if i + 1 >= n:
                        break  # need more input to disambiguate
                    if self._buf[i + 1].isdigit():
                        i += 1
                        continue
                candidate = self._buf[start : i + 1].strip()
                if len(candidate) >= _MIN_LEN:
                    out.append(candidate)
                    start = i + 1
            i += 1
        self._buf = self._buf[start:]
        return out

    def flush(self) -> List[str]:
        leftover = self._buf.strip()
        self._buf = ""
        if not leftover:
            return []
        return [leftover]
