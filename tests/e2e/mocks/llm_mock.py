"""Deterministic LLM mock for tests / e2e: enabled via env LLM_MOCK=1.

This is the on-process hook used by server.coach_realtime when LLM_MOCK=1 is set.
It is intentionally a no-op module — coach_realtime checks the env var directly
and returns canned utterances without calling the real LLM. This file exists so
the PRD-required path tests/e2e/mocks/llm_mock.py is documented and importable.
"""
from server import coach_realtime


def install():
    """No-op: coach_realtime keys off LLM_MOCK env at call time."""
    return coach_realtime._mock_utterance


CANNED_OPENING_KEYWORD = "tools and APIs"
END_SENTINEL = coach_realtime.END_SENTINEL
