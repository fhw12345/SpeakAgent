from autopilot.digest import write_digest
from autopilot.loop import LoopResult


def test_write_digest_creates_dated_file(tmp_path):
    results = [
        LoopResult(status="committed", item_slug="fix-a", branch="autopilot/2026-05-12-fix-a"),
        LoopResult(status="needs_human", item_slug="fix-b", detail="verify_failed"),
        LoopResult(status="idle"),
    ]
    out = write_digest(results, runs_dir=str(tmp_path), date_str="2026-05-12")
    assert out.endswith("digest-2026-05-12.md")
    body = open(out, encoding="utf-8").read()
    assert "fix-a" in body
    assert "fix-b" in body
    assert "committed" in body
    assert "needs_human" in body
