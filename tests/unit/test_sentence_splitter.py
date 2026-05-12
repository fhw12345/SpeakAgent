"""Unit tests for SentenceAccumulator."""
from server.sentence_splitter import SentenceAccumulator


def test_splits_on_period():
    acc = SentenceAccumulator()
    out = acc.push("Hello there. How are you?")
    # Last terminator is end-of-buffer so it's deferred until flush/next push.
    assert out == ["Hello there."]
    assert acc.flush() == ["How are you?"]


def test_splits_on_newline():
    acc = SentenceAccumulator()
    out = acc.push("Line one\nLine two\n")
    assert out == ["Line one", "Line two"]


def test_preserves_trailing_partial():
    acc = SentenceAccumulator()
    out = acc.push("Hello there. Tell me")
    assert out == ["Hello there."]
    out2 = acc.push(" more about it. ")
    # The trailing '.' followed by ' ' (non-alnum lookahead) splits now.
    assert out2 == ["Tell me more about it."]


def test_min_length_protects_abbreviations():
    """'Mr.' should not split since the period is at index 2 (< min len 4)."""
    acc = SentenceAccumulator()
    out = acc.push("Mr. Smith arrived.")
    # 'Mr.' alone is too short; final period is at end-of-buffer so it's
    # deferred until flush.
    assert out == []
    assert acc.flush() == ["Mr. Smith arrived."]


def test_min_length_protects_decimals():
    acc = SentenceAccumulator()
    out = acc.push("Pi is 3.14 roughly.")
    # The '.' inside '3.14' has alnum lookahead so it doesn't split; the
    # trailing '.' is at end-of-buffer so it's deferred until flush.
    assert out == []
    assert acc.flush() == ["Pi is 3.14 roughly."]


def test_flush_returns_leftover():
    acc = SentenceAccumulator()
    acc.push("Done. And then")
    leftover = acc.flush()
    assert leftover == ["And then"]


def test_flush_empty_when_no_leftover():
    acc = SentenceAccumulator()
    out = acc.push("All done. ")  # trailing space gives lookahead, splits.
    assert out == ["All done."]
    assert acc.flush() == []


def test_question_and_exclamation():
    acc = SentenceAccumulator()
    out = acc.push("Wow! Really? Yes.")
    # Final '.' is end-of-buffer so it's deferred until flush.
    assert out == ["Wow!", "Really?"]
    assert acc.flush() == ["Yes."]


def test_incremental_chunks():
    acc = SentenceAccumulator()
    pieces = ["Hi ", "there", ". How ", "are you?", " Tell ", "me more."]
    sentences = []
    for p in pieces:
        sentences.extend(acc.push(p))
    sentences.extend(acc.flush())
    assert sentences == ["Hi there.", "How are you?", "Tell me more."]
