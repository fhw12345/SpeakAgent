from autopilot.triggers.from_test_fails import discover, parse_pytest_failures


SAMPLE = """
============================= test session starts =============================
collected 7 items

tests/unit/test_coach.py::test_advance_from_idle_to_speak_prompt PASSED
tests/unit/test_coach.py::test_user_turn_transitions_to_listen_then_score FAILED

================================== FAILURES ===================================
______ test_user_turn_transitions_to_listen_then_score ______
AssertionError: state should be LISTEN_USER

tests/unit/test_scorer.py::test_wer_one_substitution FAILED

================================== FAILURES ===================================
___________________ test_wer_one_substitution ___________________
AssertionError: 0.0 != 0.5

============================ 2 failed, 5 passed ===============================
"""


def test_parse_pytest_failures_extracts_node_ids():
    failures = parse_pytest_failures(SAMPLE)
    ids = {f["nodeid"] for f in failures}
    assert "tests/unit/test_coach.py::test_user_turn_transitions_to_listen_then_score" in ids
    assert "tests/unit/test_scorer.py::test_wer_one_substitution" in ids


def test_discover_files_one_backlog_item_per_failure(tmp_path):
    log = tmp_path / "pytest.log"
    log.write_text(SAMPLE)
    items = discover(pytest_log=str(log))
    assert len(items) == 2
    slugs = {i.slug for i in items}
    assert any("test_user_turn" in s for s in slugs)
