import json
from autopilot.triggers.from_eval_drift import discover


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_no_item_when_no_regression(tmp_path):
    _write(tmp_path / "baseline.json", {"pass_rate": 0.90})
    _write(tmp_path / "current.json",  {"pass_rate": 0.91})
    items = discover(baseline=str(tmp_path / "baseline.json"), current=str(tmp_path / "current.json"))
    assert items == []


def test_files_high_priority_item_when_drop_over_5pct(tmp_path):
    _write(tmp_path / "baseline.json", {"pass_rate": 0.90})
    _write(tmp_path / "current.json",  {"pass_rate": 0.83})
    items = discover(baseline=str(tmp_path / "baseline.json"), current=str(tmp_path / "current.json"))
    assert len(items) == 1
    assert items[0].priority >= 9


def test_no_files_present_returns_empty(tmp_path):
    items = discover(baseline=str(tmp_path / "x.json"), current=str(tmp_path / "y.json"))
    assert items == []
