import json
from autopilot.triggers.from_session_logs import discover


def _write_session(path, turns):
    with open(path, "w", encoding="utf-8") as f:
        for t in turns:
            f.write(json.dumps(t) + "\n")


def test_no_item_when_below_threshold(tmp_path):
    _write_session(tmp_path / "s1.jsonl", [
        {"role": "user", "text": "x", "score": {"content_score": 2, "issues": ["filler"]}},
    ])
    items = discover(sessions_dir=str(tmp_path), threshold=3)
    assert items == []


def test_files_item_at_threshold(tmp_path):
    for i in range(3):
        _write_session(tmp_path / f"s{i}.jsonl", [
            {"role": "user", "text": "x", "score": {"content_score": 2, "issues": ["filler"]}},
        ])
    items = discover(sessions_dir=str(tmp_path), threshold=3)
    assert len(items) == 1
    assert "filler" in items[0].prompt.lower()


def test_multiple_distinct_issues_yield_distinct_items(tmp_path):
    for i in range(3):
        _write_session(tmp_path / f"a{i}.jsonl", [
            {"role": "user", "text": "x", "score": {"content_score": 2, "issues": ["filler"]}},
        ])
    for i in range(3):
        _write_session(tmp_path / f"b{i}.jsonl", [
            {"role": "user", "text": "x", "score": {"content_score": 1, "issues": ["wer-too-high"]}},
        ])
    items = discover(sessions_dir=str(tmp_path), threshold=3)
    assert len(items) == 2
