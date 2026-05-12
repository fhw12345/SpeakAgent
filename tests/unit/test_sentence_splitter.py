"""Unit tests for SentenceAccumulator."""
from server.sentence_splitter import SentenceAccumulator


def test_basic_three_sentences():
    acc = SentenceAccumulator()
    out = acc.push("Hello there. How are you? I am fine.")
    assert len(out) == 3
    assert out[0].endswith(".")
    assert "How are you?" in out[1]
    assert acc.flush() == []


def test_incremental_deltas():
    acc = SentenceAccumulator()
    assert acc.push("Hi") == []
    assert acc.push(" the") == []
    out = acc.push("re. Next")
    assert len(out) == 1
    assert "Hi there." in out[0]
    out2 = acc.push(" sentence!")
    assert len(out2) == 1
    assert out2[0].endswith("!")


def test_newline_terminates():
    acc = SentenceAccumulator()
    out = acc.push("Line one\nLine two!")
    assert len(out) == 2


def test_min_length_avoids_abbreviation():
    acc = SentenceAccumulator()
    out = acc.push("Mr. Smith arrived.")
    assert len(out) == 1
    assert out[0] == "Mr. Smith arrived."


def test_min_length_avoids_decimal():
    acc = SentenceAccumulator()
    out = acc.push("Pi is 3.14 roughly.")
    assert len(out) == 1


def test_flush_returns_leftover():
    acc = SentenceAccumulator()
    acc.push("partial without terminator")
    leftover = acc.flush()
    assert leftover == ["partial without terminator"]
    assert acc.flush() == []


def test_question_and_exclaim():
    acc = SentenceAccumulator()
    out = acc.push("Really? Yes!")
    assert len(out) == 2
