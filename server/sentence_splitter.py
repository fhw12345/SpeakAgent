"""Incremental sentence accumulator for streaming LLM output.

Splits on '.', '!', '?', or newline. Minimum 4 chars per sentence so
fragments like 'Mr.' or '3.14' don't trigger a split mid-token.
"""
from typing import List

_TERMINATORS = ".!?\n"
_MIN_LEN = 4


class SentenceAccumulator:
    def __init__(self) -> None:
        self._buf: str = ""

    def push(self, delta: str) -> List[str]:
        """Append delta; return any newly-completed sentences (in order)."""
        self._buf += delta
        out: List[str] = []
        while True:
            idx = self._find_split()
            if idx < 0:
                break
            sentence = self._buf[: idx + 1].strip()
            self._buf = self._buf[idx + 1 :]
            if sentence:
                out.append(sentence)
        return out

    def _find_split(self) -> int:
        """Return index of the next valid sentence-ending terminator, or -1.

        A terminator is valid when:
        - it sits at position >= _MIN_LEN - 1 (so 'Mr.' alone won't split),
        - and, for '.' '?' '!', the next character (if any) is not alphanumeric
          (so '3.14' and 'e.g.x' don't split mid-token).
        Newlines always split when the min-length rule is satisfied.
        """
        for i, ch in enumerate(self._buf):
            if ch not in _TERMINATORS:
                continue
            if i + 1 < _MIN_LEN:
                continue
            if ch == "\n":
                return i
            if i + 1 >= len(self._buf):
                # Need lookahead to know if this is e.g. '3.14'; defer.
                return -1
            nxt = self._buf[i + 1]
            if nxt.isalnum():
                continue
            return i
        return -1

    def flush(self) -> List[str]:
        """Return any remaining buffered text as a final sentence (or [])."""
        leftover = self._buf.strip()
        self._buf = ""
        return [leftover] if leftover else []
