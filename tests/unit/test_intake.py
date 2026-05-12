import json
from unittest.mock import patch
from autopilot.intake import generate_backlog_items, generate_prd, _slugify


def test_slugify_basic():
    assert _slugify("Hello World") == "hello-world"
    assert _slugify("做阶段 1 session 列表 UI") == "做阶段-1-session-列表-ui"
    assert _slugify("") != ""  # falls back to uuid


def test_generate_backlog_items_parses_clean_json():
    fake_llm = json.dumps([
        {"slug": "scaffold", "priority": 9, "prompt": "create file X"},
        {"slug": "wire", "priority": 5, "prompt": "wire route Y"},
    ])
    with patch("autopilot.intake._llm_call", return_value=fake_llm):
        items = generate_backlog_items("PRD CONTENT", "autopilot/prds/test.md")
    assert len(items) == 2
    assert items[0].slug == "scaffold"
    assert items[0].priority == 9
    assert items[0].source == "intake"
    assert "intake" in items[0].tags
    assert "autopilot/prds/test.md" in items[0].prompt
    assert "create file X" in items[0].prompt


def test_generate_backlog_items_strips_code_fences():
    fake_llm = "```json\n" + json.dumps([{"slug": "a", "priority": 1, "prompt": "p"}]) + "\n```"
    with patch("autopilot.intake._llm_call", return_value=fake_llm):
        items = generate_backlog_items("PRD", "p.md")
    assert len(items) == 1
    assert items[0].slug == "a"


def test_generate_backlog_items_raises_on_bad_json():
    with patch("autopilot.intake._llm_call", return_value="not json"):
        try:
            generate_backlog_items("PRD", "p.md")
        except ValueError as e:
            assert "JSON" in str(e)
            return
    assert False, "expected ValueError"


def test_generate_prd_rejects_short_response(tmp_path):
    """LLM error string (e.g. 96-char graceful) must NOT be written as a PRD."""
    with patch("autopilot.intake._llm_call", return_value="oops short"):
        try:
            generate_prd("anything", str(tmp_path / "prd.md"))
        except RuntimeError as e:
            assert "short" in str(e).lower()
            return
    assert False, "expected RuntimeError on suspiciously short PRD"


def test_generate_prd_writes_file_on_good_response(tmp_path):
    fake = "## Goal\nDo X.\n\n## Acceptance Criteria\n1. ...\n" + ("blah " * 60)
    prd_path = tmp_path / "prd.md"
    with patch("autopilot.intake._llm_call", return_value=fake):
        md = generate_prd("do X", str(prd_path))
    assert prd_path.exists()
    body = prd_path.read_text(encoding="utf-8")
    assert "# PRD: do X" in body
    assert "## Goal" in body
    assert md == fake
