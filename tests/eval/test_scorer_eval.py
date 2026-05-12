# tests/eval/test_scorer_eval.py
import pytest
from unittest.mock import patch
from server.scorer import score_turn
from tests.eval.fixtures import FIXTURES


@pytest.mark.parametrize("fx", FIXTURES, ids=[f["id"] for f in FIXTURES])
def test_scorer_fixture(fx):
    with patch("server.scorer.call_with_fallback", return_value=fx["fake_judge"]):
        s = score_turn(
            user_text=fx["user_text"],
            user_words=fx["words"],
            user_confidence=fx["confidence"],
            ideal_text=fx["ideal"],
        )
    lo, hi = fx["pron_range"]
    assert lo <= s.pronunciation <= hi, f"{fx['id']}: pronunciation {s.pronunciation} not in {fx['pron_range']}"
    assert s.content_score == fx["expected_content_score"]
