"""Unit tests for SentenceAccumulator."""
from server.sentence_splitter import SentenceAccumulator


def test_basic_period_cut():
    acc = SentenceAccumulator()
    # Trailing '?' has no lookahead until next push or flush.
    out = acc.push("Hello world. How are you?")
    assert out == ["Hello world."]
    assert acc.flush() == ["How are you?"]


def test_min_length_protects_abbreviation():
    acc = SentenceAccumulator()
    # "Mr." stripped -> 3 chars < min_len 4, so the first '.' does not cut.
    out = acc.push("Mr. Smith said hi.")
    # Trailing '.' has no lookahead -> waits.
    assert out == []
    assert acc.flush() == ["Mr. Smith said hi."]


def test_decimal_lookahead_blocks_cut():
    acc = SentenceAccumulator()
    # "3.14" -> first '.' followed by digit (non-space, non-terminator) -> no cut.
    out = acc.push("Pi is 3.14 exactly. Done.")
    assert out == ["Pi is 3.14 exactly."]
    assert acc.flush() == ["Done."]


def test_partial_then_flush():
    acc = SentenceAccumulator()
    assert acc.push("Hi.") == []  # no lookahead yet
    assert acc.flush() == ["Hi."]


def test_incremental_delta():
    acc = SentenceAccumulator()
    a = acc.push("Hel")
    b = acc.push("lo world")
    # The '.' is followed by ' ' in this same chunk -> cut now.
    c = acc.push(". Next")
    d = acc.push(" sentence here.")
    e = acc.flush()
    assert a == [] and b == []
    assert c == ["Hello world."]
    assert d == []
    assert e == ["Next sentence here."]


def test_newline_terminator():
    acc = SentenceAccumulator()
    # newline terminator: needs lookahead just like '.'.
    out = acc.push("First line\nsecond.")
    # '\n' lookahead is 's' -> not whitespace/terminator -> no cut on '\n'.
    # Hmm: per rules, lookahead must be whitespace/terminator. 's' is not. So '\n' doesn't cut here.
    # That matches the plan: newline acts as both terminator and separator when followed by space/EOL.
    # Let's verify a clearer case:
    out2 = acc.push("\nthird.")
    # After flush:
    out3 = acc.flush()
    # The combined buffer is "First line\nsecond.\nthird."
    # '\n' at pos 10 lookahead 's' -> no cut
    # '.' at pos 17 lookahead '\n' (terminator) -> cut "First line\nsecond."
    # '\n' at pos 18 lookahead 't' -> no cut
    # '.' final -> no lookahead -> wait -> flush returns it
    combined = out + out2 + out3
    assert "First line\nsecond." in combined
    assert "third." in combined


def test_question_and_exclaim():
    acc = SentenceAccumulator()
    out = acc.push("Wow! Really? Yes.")
    assert acc.flush() == ["Yes."]
    assert out == ["Wow!", "Really?"]


def test_multiple_pushes_three_sentences():
    acc = SentenceAccumulator()
    deltas = ["Hi ", "there. ", "How ", "are you?", " Tell ", "me more."]
    collected: list = []
    for d in deltas:
        collected.extend(acc.push(d))
    collected.extend(acc.flush())
    assert collected == ["Hi there.", "How are you?", "Tell me more."]
