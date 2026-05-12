import json
from unittest.mock import patch
from autopilot.triggers.from_repo_scan import discover


def _personal(tmp_path, entries):
    p = tmp_path / "personal_projects.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return str(p)


def test_no_recent_commits_returns_no_item(tmp_path):
    pj = _personal(tmp_path, [{"id": "x", "name": "X", "repo_path": "/non/existent"}])
    with patch("autopilot.triggers.from_repo_scan._git_log_since", return_value=""):
        items = discover(personal_projects_path=pj)
    assert items == []


def test_recent_commits_with_keyword_files_proposal(tmp_path):
    pj = _personal(tmp_path, [{"id": "x", "name": "X", "repo_path": "/non/existent"}])
    with patch("autopilot.triggers.from_repo_scan._git_log_since",
               return_value="abc123 add new RAG retrieval mode\ndef456 implement reranker\n"):
        items = discover(personal_projects_path=pj)
    assert len(items) == 1
    assert "needs-human" in items[0].tags
    assert "X" in items[0].prompt
