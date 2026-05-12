from unittest.mock import patch, MagicMock
from autopilot.loop import run_once, LoopResult
from autopilot.backlog import Item


def test_run_once_returns_paused_when_pause_present(tmp_path):
    pause = tmp_path / "PAUSE"
    pause.write_text("")
    res = run_once(pause_path=str(pause))
    assert res.status == "paused"


def test_run_once_returns_idle_when_no_items(tmp_path):
    with patch("autopilot.loop._collect_all_triggers", return_value=[]):
        res = run_once(pause_path=str(tmp_path / "PAUSE"),
                       backlog_path=str(tmp_path / "b.jsonl"))
    assert res.status == "idle"


def test_run_once_dispatches_picked_item(tmp_path):
    item = Item(slug="fix-x", priority=10, source="test_fails", prompt="fix x")
    fake_proc = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("autopilot.loop._collect_all_triggers", return_value=[item]), \
         patch("autopilot.loop._make_worktree", return_value=str(tmp_path / "wt")), \
         patch("autopilot.loop._spawn_claude", return_value=fake_proc) as spawn, \
         patch("autopilot.loop._verify", return_value=True), \
         patch("autopilot.loop._commit_to_branch", return_value="autopilot/2026-05-12-fix-x"):
        res = run_once(pause_path=str(tmp_path / "PAUSE"),
                       backlog_path=str(tmp_path / "b.jsonl"))
    assert res.status == "committed"
    assert res.branch == "autopilot/2026-05-12-fix-x"
    spawn.assert_called_once()


def test_failed_verify_files_needs_human(tmp_path):
    item = Item(slug="fix-y", priority=10, source="test_fails", prompt="fix y")
    fake_proc = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("autopilot.loop._collect_all_triggers", return_value=[item]), \
         patch("autopilot.loop._make_worktree", return_value=str(tmp_path / "wt")), \
         patch("autopilot.loop._spawn_claude", return_value=fake_proc), \
         patch("autopilot.loop._verify", return_value=False):
        res = run_once(pause_path=str(tmp_path / "PAUSE"),
                       backlog_path=str(tmp_path / "b.jsonl"))
    assert res.status == "needs_human"
