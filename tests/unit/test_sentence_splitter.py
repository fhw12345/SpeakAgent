from server.sentence_splitter import SentenceAccumulator


def test_splits_on_period():
    a = SentenceAccumulator()
    out = a.push("Hello world. How are you?")
    assert out == ["Hello world.", "How are you?"]


def test_splits_on_newline():
    a = SentenceAccumulator()
    out = a.push("Line one\nLine two more")
    assert out == ["Line one"]
    assert a.flush() == ["Line two more"]


def test_preserves_trailing_partial():
    a = SentenceAccumulator()
    out = a.push("First sentence. Second part")
    assert out == ["First sentence."]
    assert a.flush() == ["Second part"]


def test_min_length_4_rejects_mr():
    a = SentenceAccumulator()
    out = a.push("Mr. Smith arrived early.")
    # "Mr." is 3 chars stripped — must NOT split there.
    assert out == ["Mr. Smith arrived early."]


def test_min_length_4_rejects_decimal():
    a = SentenceAccumulator()
    out = a.push("Pi is 3.14 approximately.")
    assert out == ["Pi is 3.14 approximately."]


def test_question_and_exclamation():
    a = SentenceAccumulator()
    out = a.push("Really? Yes! Indeed.")
    assert out == ["Really?", "Yes!", "Indeed."]


def test_incremental_pushes():
    a = SentenceAccumulator()
    assert a.push("Hello") == []
    assert a.push(" world") == []
    assert a.push(". Next") == ["Hello world."]
    assert a.push(" one.") == ["Next one."]


def test_flush_empty():
    a = SentenceAccumulator()
    assert a.flush() == []


def test_flush_strips_whitespace():
    a = SentenceAccumulator()
    a.push("  partial   ")
    assert a.flush() == ["partial"]


def test_empty_push():
    a = SentenceAccumulator()
    assert a.push("") == []
