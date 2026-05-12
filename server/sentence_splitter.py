"""Incremental sentence accumulator for streaming LLM output.

Splits on `.`, `!`, `?`, or newline once the buffered sentence has at least
MIN_LEN non-whitespace characters. Suppresses period splits when the period
follows a digit (decimal number like `3.14`) or a known short abbreviation
(`Mr.`, `Dr.`, `Ms.`).
"""
from typing import List

MIN_LEN = 4
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "jr", "sr", "prof", "vs", "etc"}


def _prev_is_digit(buf: list[str]) -> bool:
    if len(buf) < 2:
        return False
    return buf[-2].isdigit()


def _looks_like_abbrev(buf: list[str]) -> bool:
    if not buf or buf[-1] != ".":
        return False
    word_chars: list[str] = []
    for ch in reversed(buf[:-1]):
        if ch.isalpha():
            word_chars.append(ch)
        else:
            break
    if not word_chars:
        return False
    return "".join(reversed(word_chars)).lower() in ABBREVIATIONS


class SentenceAccumulator:
    def __init__(self) -> None:
        self._buf: list[str] = []

    def _ready(self) -> bool:
        candidate = "".join(self._buf).strip()
        return len(candidate.replace(" ", "")) >= MIN_LEN

    def _flush_buf(self) -> str | None:
        text = "".join(self._buf).strip()
        self._buf = []
        return text or None

    def push(self, delta: str) -> List[str]:
        out: List[str] = []
        for ch in delta:
            self._buf.append(ch)
            if not self._ready():
                continue
            if ch == "\n" or ch in "!?":
                sentence = self._flush_buf()
                if sentence:
                    out.append(sentence)
                continue
            if ch == ".":
                if _prev_is_digit(self._buf):
                    continue
                if _looks_like_abbrev(self._buf):
                    continue
                sentence = self._flush_buf()
                if sentence:
                    out.append(sentence)
        return out

    def flush(self) -> List[str]:
        leftover = "".join(self._buf).strip()
        self._buf = []
        if leftover:
            return [leftover]
        return []
