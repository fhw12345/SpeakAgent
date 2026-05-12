from autopilot.backlog import Backlog, Item


def test_add_and_pick_highest_priority(tmp_path):
    b = Backlog(path=str(tmp_path / "backlog.jsonl"))
    b.add(Item(slug="a", priority=1, source="test_fails", prompt="fix a"))
    b.add(Item(slug="b", priority=10, source="eval_drift", prompt="fix b"))
    b.add(Item(slug="c", priority=5, source="session_logs", prompt="fix c"))
    picked = b.pick()
    assert picked.slug == "b"


def test_skip_needs_human(tmp_path):
    b = Backlog(path=str(tmp_path / "backlog.jsonl"))
    b.add(Item(slug="x", priority=99, source="t", prompt="x", tags=["needs-human"]))
    b.add(Item(slug="y", priority=1, source="t", prompt="y"))
    picked = b.pick()
    assert picked.slug == "y"


def test_mark_done_removes_item(tmp_path):
    b = Backlog(path=str(tmp_path / "backlog.jsonl"))
    b.add(Item(slug="z", priority=1, source="t", prompt="z"))
    b.mark_done("z")
    assert b.pick() is None


def test_dedup_by_slug(tmp_path):
    b = Backlog(path=str(tmp_path / "backlog.jsonl"))
    b.add(Item(slug="dup", priority=1, source="t", prompt="first"))
    b.add(Item(slug="dup", priority=2, source="t", prompt="second"))
    items = b.all_open()
    assert len(items) == 1
    assert items[0].priority == 2
