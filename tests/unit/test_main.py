from unittest.mock import patch
from autopilot.main import run_loop
from autopilot.loop import LoopResult


def test_run_loop_max_iterations_bounded(tmp_path):
    pause = str(tmp_path / "PAUSE")
    fake = LoopResult(status="idle")
    with patch("autopilot.main.run_once", return_value=fake), \
         patch("autopilot.main.write_digest", return_value=str(tmp_path / "digest.md")):
        results = run_loop(interval_seconds=0, max_iterations=3, pause_path=pause)
    assert len(results) == 3
    assert all(r.status == "idle" for r in results)


def test_run_loop_paused_state_propagates(tmp_path):
    pause = tmp_path / "PAUSE"
    pause.write_text("")
    with patch("autopilot.main.write_digest", return_value=str(tmp_path / "digest.md")):
        results = run_loop(interval_seconds=0, max_iterations=2, pause_path=str(pause))
    assert len(results) == 2
    assert all(r.status == "paused" for r in results)


def test_run_loop_writes_digest_on_meaningful_events(tmp_path):
    pause = str(tmp_path / "PAUSE")
    fake = LoopResult(status="committed", item_slug="x", branch="autopilot/x")
    digest_calls = []
    def fake_digest(results, **kwargs):
        digest_calls.append(len(results))
        return str(tmp_path / "digest.md")
    with patch("autopilot.main.run_once", return_value=fake), \
         patch("autopilot.main.write_digest", side_effect=fake_digest):
        run_loop(interval_seconds=0, max_iterations=2, pause_path=pause)
    # 2 mid-loop writes (one per committed result) + 1 shutdown write = 3
    assert len(digest_calls) == 3


def test_run_loop_handles_run_once_exception_gracefully(tmp_path):
    pause = str(tmp_path / "PAUSE")
    with patch("autopilot.main.run_once", side_effect=RuntimeError("boom")), \
         patch("autopilot.main.write_digest", return_value=str(tmp_path / "digest.md")):
        results = run_loop(interval_seconds=0, max_iterations=2, pause_path=pause)
    assert len(results) == 2
    assert all(r.status == "error" for r in results)
    assert "boom" in results[0].detail


def test_run_loop_idle_does_not_spam_digest(tmp_path):
    pause = str(tmp_path / "PAUSE")
    fake = LoopResult(status="idle")
    digest_calls = []
    def fake_digest(results, **kwargs):
        digest_calls.append(len(results))
        return str(tmp_path / "digest.md")
    with patch("autopilot.main.run_once", return_value=fake), \
         patch("autopilot.main.write_digest", side_effect=fake_digest):
        run_loop(interval_seconds=0, max_iterations=5, pause_path=pause)
    # 5 idle ticks should NOT trigger mid-loop writes; only 1 shutdown write
    assert len(digest_calls) == 1
