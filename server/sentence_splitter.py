"""Incremental sentence accumulator for streaming LLM output.

Consumes text deltas, returns completed sentences as soon as a terminator
(`.`, `!`, `?`, or newline) appears. Two heuristics avoid false splits:

  1. Min-length 4: a candidate sentence shorter than 4 chars (e.g. `Mr.`)
     does not terminate; the terminator is replaced with a space.
  2. Decimal guard: `.` followed immediately by a digit (e.g. `3.14`) is
     not a terminator.
"""
from typing import List

_TERMINATORS = ".!?\n"
_MIN_LEN = 4


class SentenceAccumulator:
    def __init__(self) -> None:
        self._buf: str = ""

    def push(self, delta: str) -> List[str]:
        self._buf += delta
        out: List[str] = []
        i = 0
        while i < len(self._buf):
            ch = self._buf[i]
            if ch not in _TERMINATORS:
                i += 1
                continue
            # Decimal guard: `.` followed by a digit isn't a sentence end.
            if ch == "." and i + 1 < len(self._buf) and self._buf[i + 1].isdigit():
                i += 1
                continue
            candidate = self._buf[: i + 1].strip()
            if len(candidate) < _MIN_LEN:
                self._buf = self._buf[:i] + " " + self._buf[i + 1 :]
                i += 1
                continue
            out.append(candidate)
            self._buf = self._buf[i + 1 :]
            i = 0
        return out

    def flush(self) -> List[str]:
        leftover = self._buf.strip()
        self._buf = ""
        if leftover:
            return [leftover]
        return []
