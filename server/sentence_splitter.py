"""Incremental sentence accumulator for streaming LLM output.

Splits on `.`, `!`, `?`, or `\n` when the terminator is followed by whitespace
or end-of-buffer. Sentences shorter than MIN_LEN characters (after stripping)
do not split — this swallows abbreviations like `Mr.` and decimals like `3.14`
into the next chunk rather than emitting them alone.
"""
from __future__ import annotations

MIN_LEN = 4
_TERMINATORS = ".!?\n"


class SentenceAccumulator:
    def __init__(self) -> None:
        self._buf: str = ""

    def push(self, delta: str) -> list[str]:
        """Append delta; return any newly completed sentences (in order)."""
        self._buf += delta
        out: list[str] = []
        scan_from = 0
        while True:
            idx = self._next_break(self._buf, scan_from)
            if idx < 0:
                break
            candidate = self._buf[: idx + 1].strip()
            if len(candidate) < MIN_LEN:
                # Too short — skip this terminator, keep scanning.
                scan_from = idx + 1
                continue
            out.append(candidate)
            self._buf = self._buf[idx + 1 :]
            scan_from = 0
        return out

    def flush(self) -> list[str]:
        """Return whatever remains as a final sentence (if non-empty)."""
        rest = self._buf.strip()
        self._buf = ""
        return [rest] if rest else []

    @staticmethod
    def _next_break(s: str, start: int) -> int:
        """Index of next terminator at position i where s[i+1] is whitespace,
        a terminator, or end-of-string. Newlines always count."""
        for i in range(start, len(s)):
            c = s[i]
            if c == "\n":
                return i
            if c in ".!?":
                nxt = s[i + 1] if i + 1 < len(s) else ""
                if nxt == "" or nxt.isspace() or nxt in _TERMINATORS:
                    return i
        return -1
