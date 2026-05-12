from server.sentence_splitter import SentenceAccumulator


def test_single_complete_sentence_emits_after_followup_space():
    acc = SentenceAccumulator()
    assert acc.push("Hello world.") == []
    assert acc.push(" ") == ["Hello world."]


def test_single_complete_sentence_via_flush():
    acc = SentenceAccumulator()
    assert acc.push("Hello world.") == []
    assert acc.flush() == ["Hello world."]


def test_partial_sentence_buffered_until_terminator():
    acc = SentenceAccumulator()
    assert acc.push("Hello ") == []
    assert acc.push("world") == []
    assert acc.push(". ") == ["Hello world."]


def test_multi_sentence_input_in_one_push():
    acc = SentenceAccumulator()
    out = acc.push("Hi there. How are you? Tell me more!")
    assert out == ["Hi there.", "How are you?", "Tell me more!"]


def test_multi_sentence_input_across_multiple_pushes():
    acc = SentenceAccumulator()
    out1 = acc.push("Hi there. How ar")
    out2 = acc.push("e you? Tell me more!")
    assert out1 == ["Hi there."]
    assert out2 == ["How are you?", "Tell me more!"]


def test_trailing_partial_preserved_between_pushes():
    acc = SentenceAccumulator()
    assert acc.push("Hello world. And then") == ["Hello world."]
    assert acc.push(" more text.") == []
    assert acc.flush() == ["And then more text."]


def test_flush_returns_leftover():
    acc = SentenceAccumulator()
    acc.push("Hello world. partial fragment")
    assert acc.flush() == ["partial fragment"]


def test_flush_returns_empty_after_clean_terminator_with_followup():
    acc = SentenceAccumulator()
    acc.push("Hello world. ")
    assert acc.flush() == []


def test_flush_returns_empty_when_buffer_only_whitespace():
    acc = SentenceAccumulator()
    acc.push("   ")
    assert acc.flush() == []


def test_abbreviation_mr_does_not_split():
    acc = SentenceAccumulator()
    out = acc.push("Mr. Smith went home. ")
    assert out == ["Mr. Smith went home."]


def test_decimal_number_does_not_split():
    acc = SentenceAccumulator()
    out = acc.push("Pi is 3.14 approximately. ")
    assert out == ["Pi is 3.14 approximately."]


def test_decimal_split_across_pushes_does_not_split_prematurely():
    acc = SentenceAccumulator()
    assert acc.push("Pi is 3.") == []
    assert acc.push("14 approximately. ") == ["Pi is 3.14 approximately."]


def test_newline_is_a_terminator_emitted_immediately():
    acc = SentenceAccumulator()
    out = acc.push("First line here\nSecond line here\n")
    assert out == ["First line here", "Second line here"]


def test_question_mark_emits_immediately_at_end_of_buffer():
    acc = SentenceAccumulator()
    out = acc.push("Are you ok?")
    assert out == ["Are you ok?"]


def test_exclamation_emits_immediately_at_end_of_buffer():
    acc = SentenceAccumulator()
    out = acc.push("Watch out!")
    assert out == ["Watch out!"]


def test_mixed_terminators_period_question_exclaim_newline():
    acc = SentenceAccumulator()
    out = acc.push("Hello there. Are you ok? Yes!\nBye now. ")
    assert out == ["Hello there.", "Are you ok?", "Yes!", "Bye now."]


def test_short_sentence_under_min_length_does_not_split():
    acc = SentenceAccumulator()
    assert acc.push("Hi. There everyone. ") == ["Hi. There everyone."]


def test_empty_push_returns_empty():
    acc = SentenceAccumulator()
    assert acc.push("") == []


def test_only_whitespace_pushed_then_flushed_returns_empty():
    acc = SentenceAccumulator()
    acc.push("   \n  ")
    assert acc.flush() == []


def test_leading_whitespace_between_sentences_stripped():
    acc = SentenceAccumulator()
    out = acc.push("First sentence.   Second sentence. ")
    assert out == ["First sentence.", "Second sentence."]
