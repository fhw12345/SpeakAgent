from unittest.mock import patch, MagicMock
from autopilot.loop import run_once, LoopResult, _claude_executable, _spawn_claude
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


def test_claude_executable_resolves_via_shutil_which():
    with patch("shutil.which", side_effect=lambda name: f"/fake/{name}" if name == "claude" else None):
        assert _claude_executable() == "/fake/claude"


def test_claude_executable_falls_back_to_cmd_on_windows():
    def fake_which(name):
        return "/fake/claude.cmd" if name == "claude.cmd" else None
    with patch("shutil.which", side_effect=fake_which):
        assert _claude_executable() == "/fake/claude.cmd"


def test_claude_executable_raises_when_missing():
    with patch("shutil.which", return_value=None):
        try:
            _claude_executable()
        except RuntimeError as e:
            assert "claude" in str(e).lower()
            return
    assert False, "expected RuntimeError"


def test_spawn_claude_uses_opus_and_bypass_permissions(tmp_path):
    item = Item(slug="x", priority=1, source="t", prompt="do thing")
    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return MagicMock(returncode=0, stdout="", stderr="")
    with patch("autopilot.loop._claude_executable", return_value="/fake/claude"), \
         patch("subprocess.run", side_effect=fake_run):
        _spawn_claude(item, str(tmp_path))
    assert captured["cmd"][0] == "/fake/claude"
    assert "-p" in captured["cmd"]
    assert "--model" in captured["cmd"]
    assert "opus" in captured["cmd"]
    assert "--permission-mode" in captured["cmd"]
    assert "bypassPermissions" in captured["cmd"]
    assert captured["cmd"][-1] == "do thing"
    assert captured["cwd"] == str(tmp_path)
