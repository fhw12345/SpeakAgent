import os
import json
import tempfile
from datetime import date, timedelta
from server.progress import ProgressStore, sm2_next


def test_sm2_quality_5_increases_interval():
    nxt = sm2_next(prev_interval=1, prev_ease=2.5, quality=5)
    assert nxt["interval_days"] >= 6
    assert nxt["ease"] >= 2.5


def test_sm2_quality_2_resets_to_one_day():
    nxt = sm2_next(prev_interval=10, prev_ease=2.5, quality=2)
    assert nxt["interval_days"] == 1


def test_session_append_and_read(tmp_path):
    store = ProgressStore(data_dir=str(tmp_path))
    sid = "s1"
    store.append_turn(sid, "lesson1", {"role": "user", "text": "hello", "score": {"content_score": 4}})
    store.append_turn(sid, "lesson1", {"role": "agent", "text": "hi back"})
    turns = store.read_session(sid)
    assert len(turns) == 2
    assert turns[0]["role"] == "user"


def test_vocab_srs_add_and_due(tmp_path):
    store = ProgressStore(data_dir=str(tmp_path))
    store.add_words(["heterogeneous", "consensus"])
    due = store.due_words(today=date.today() + timedelta(days=1))
    assert "heterogeneous" in due
    assert "consensus" in due


def test_vocab_srs_review_pushes_due_date(tmp_path):
    store = ProgressStore(data_dir=str(tmp_path))
    store.add_words(["adjudication"])
    store.review_word("adjudication", quality=5)
    due_today = store.due_words(today=date.today())
    assert "adjudication" not in due_today
