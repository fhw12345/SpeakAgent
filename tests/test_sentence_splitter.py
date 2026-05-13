"""Unit tests for SentenceAccumulator."""
from server.sentence_splitter import SentenceAccumulator


def test_splits_on_period():
    s = SentenceAccumulator()
    out = []
    out += s.push("Hello there. ")
    out += s.push("How are you?")
    assert out == ["Hello there.", "How are you?"]


def test_preserves_trailing_partial():
    s = SentenceAccumulator()
    out = s.push("Hello there. And then")
    assert out == ["Hello there."]
    assert s.flush() == ["And then"]


def test_splits_on_exclamation_question_newline():
    s = SentenceAccumulator()
    out = []
    out += s.push("Wow! ")
    out += s.push("Really?\n")
    out += s.push("Sure thing.")
    out += s.flush()
    assert out == ["Wow!", "Really?", "Sure thing."]


def test_min_length_skips_mr_and_decimals():
    s = SentenceAccumulator()
    out = s.push("Mr. Smith arrived. ")
    assert out == ["Mr  Smith arrived."]


def test_min_length_skips_pi():
    s = SentenceAccumulator()
    out = s.push("Pi is 3.14 exactly. ")
    assert out == ["Pi is 3.14 exactly."]


def test_flush_empty():
    s = SentenceAccumulator()
    assert s.flush() == []


def test_incremental_deltas():
    s = SentenceAccumulator()
    out = []
    for ch in "Hi there. How now?":
        out += s.push(ch)
    out += s.flush()
    assert out == ["Hi there.", "How now?"]
