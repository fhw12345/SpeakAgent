from server.sentence_splitter import SentenceAccumulator


def test_basic_period():
    acc = SentenceAccumulator()
    out = acc.push("Hello world. ")
    assert out == ["Hello world."]


def test_basic_period_at_eof_requires_flush():
    acc = SentenceAccumulator()
    assert acc.push("Hello world.") == []
    assert acc.flush() == ["Hello world."]


def test_question_and_exclamation():
    acc = SentenceAccumulator()
    out = acc.push("Hi there! How are you? Tell me more. ")
    assert out == ["Hi there!", "How are you?", "Tell me more."]


def test_newline_terminator():
    acc = SentenceAccumulator()
    out = acc.push("First line\nSecond line. ")
    assert out == ["First line", "Second line."]


def test_incremental_chunks():
    acc = SentenceAccumulator()
    assert acc.push("Hel") == []
    assert acc.push("lo wo") == []
    assert acc.push("rld. Next") == ["Hello world."]
    assert acc.push(" sentence. ") == ["Next sentence."]


def test_min_length_filters_abbreviations():
    acc = SentenceAccumulator()
    out = acc.push("Mr. Smith said hi. ")
    assert out == ["Mr. Smith said hi."]


def test_min_length_filters_decimals():
    acc = SentenceAccumulator()
    out = acc.push("Pi is 3.14 exactly. ")
    assert out == ["Pi is 3.14 exactly."]


def test_flush_returns_leftover():
    acc = SentenceAccumulator()
    acc.push("Done. Trailing partial")
    assert acc.flush() == ["Trailing partial"]


def test_flush_returns_pending_terminator_at_eof():
    acc = SentenceAccumulator()
    acc.push("Done.")
    assert acc.flush() == ["Done."]


def test_flush_clears_buffer():
    acc = SentenceAccumulator()
    acc.push("partial leftover")
    assert acc.flush() == ["partial leftover"]
    assert acc.flush() == []


def test_flush_drops_too_short_leftover():
    acc = SentenceAccumulator()
    acc.push("Hi")
    assert acc.flush() == []


def test_empty_push_noop():
    acc = SentenceAccumulator()
    assert acc.push("") == []
    assert acc.flush() == []
