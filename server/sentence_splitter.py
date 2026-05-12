"""Incremental sentence accumulator for streaming LLM deltas."""
from typing import List


class SentenceAccumulator:
    """Buffer text deltas; emit completed sentences on terminator + lookahead.

    Cut iff terminator (`.!?\\n`) hit AND len(current.strip()) >= min_len AND
    lookahead char is end-of-buffer / whitespace / another terminator.
    Trailing partial is preserved across pushes; flush() returns it.
    """

    def __init__(self, terminators: str = ".!?\n", min_len: int = 4) -> None:
        self._terminators = set(terminators)
        self._min_len = min_len
        self._buf: str = ""

    def push(self, delta: str) -> List[str]:
        self._buf += delta
        out: List[str] = []
        start = 0
        i = 0
        n = len(self._buf)
        while i < n:
            ch = self._buf[i]
            if ch in self._terminators:
                current = self._buf[start:i + 1]
                # min_len applies to stripped content of the candidate sentence.
                if len(current.strip()) >= self._min_len:
                    # Lookahead: end-of-buffer means we cannot yet decide; stop and wait.
                    if i + 1 >= n:
                        break
                    look = self._buf[i + 1]
                    if look.isspace() or look in self._terminators:
                        out.append(current.strip())
                        # Skip following whitespace (trim leading space of next sentence).
                        j = i + 1
                        while j < n and self._buf[j].isspace() and self._buf[j] != "\n":
                            j += 1
                        # Newlines are themselves terminators; if look is "\n", consume it as a separator.
                        if j < n and self._buf[j] == "\n":
                            j += 1
                        start = j
                        i = j
                        continue
            i += 1
        # Keep any unconsumed tail in buffer.
        self._buf = self._buf[start:]
        return out

    def flush(self) -> List[str]:
        tail = self._buf.strip()
        self._buf = ""
        return [tail] if tail else []
