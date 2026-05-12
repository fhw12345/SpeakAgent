"""Unit tests for SentenceAccumulator."""
from server.sentence_splitter import SentenceAccumulator


def test_splits_on_period_question_exclaim_newline():
    acc = SentenceAccumulator()
    out = acc.push("Hello there. How are you? Great!\nMore text")
    assert out == ["Hello there.", "How are you?", "Great!"]
    assert acc.flush() == ["More text"]


def test_preserves_trailing_partial():
    acc = SentenceAccumulator()
    assert acc.push("This is a sentence.") == ["This is a sentence."]
    assert acc.push(" In progress") == []
    assert acc.flush() == ["In progress"]


def test_ignores_short_abbreviation_period():
    acc = SentenceAccumulator()
    out = acc.push("Mr. Smith arrived early today.")
    # "Mr." alone is < MIN_LEN (4) so it's swallowed; full sentence emitted as one.
    assert out == ["Mr. Smith arrived early today."]


def test_ignores_decimal_point():
    acc = SentenceAccumulator()
    out = acc.push("Pi is 3.14 approximately.")
    assert out == ["Pi is 3.14 approximately."]


def test_streaming_deltas():
    acc = SentenceAccumulator()
    deltas = ["Hi", " there", ". How", " are", " you", "? Done", "."]
    collected: list[str] = []
    for d in deltas:
        collected.extend(acc.push(d))
    collected.extend(acc.flush())
    assert collected == ["Hi there.", "How are you?", "Done."]


def test_flush_returns_empty_when_buffer_empty():
    acc = SentenceAccumulator()
    acc.push("Done.")
    assert acc.flush() == []
