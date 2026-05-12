from autopilot.policies import (
    load_rate_limit, RateLimiter, load_escalation, matches_escalation,
)


def test_rate_limit_default_60_per_min(tmp_path):
    p = tmp_path / "rl.yml"
    p.write_text("max_calls_per_minute: 60\npause_seconds_on_trip: 60\n")
    rl = load_rate_limit(str(p))
    assert rl.max_calls_per_minute == 60
    assert rl.pause_seconds_on_trip == 60


def test_rate_limiter_trips_after_max_calls(monkeypatch):
    limiter = RateLimiter(max_calls_per_minute=3)
    times = [1000.0, 1000.1, 1000.2, 1000.3]
    monkeypatch.setattr("time.monotonic", lambda: times.pop(0))
    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is False


def test_escalation_matches_schema_migration():
    rules = load_escalation()
    files = ["server/schema.sql", "server/main.py"]
    assert matches_escalation(rules, files=files, diff_summary="add column users.email")


def test_escalation_matches_file_deletion():
    rules = load_escalation()
    assert matches_escalation(rules, files=[], diff_summary="deleted: server/old.py")


def test_escalation_matches_autopilot_self_modification():
    rules = load_escalation()
    assert matches_escalation(rules, files=["autopilot/loop.py"], diff_summary="x")


def test_escalation_does_not_match_normal_change():
    rules = load_escalation()
    assert not matches_escalation(rules, files=["server/coach.py"], diff_summary="refactor coach state machine")
