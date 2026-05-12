"""Deterministic mock LLM helpers for e2e tests.

Reuses the canned sequence baked into `server.llm_client` (`LLM_MOCK=1`).
Exposing it here means tests can import a single source of truth for
expected utterances when asserting against the transcript pane.
"""
from server.llm_client import _MOCK_SEQUENCE


def expected_first_n_agent_utterances(n: int) -> list[str]:
    """Return the first `n` mock LLM utterances (sentinel stripped)."""
    out: list[str] = []
    for raw in _MOCK_SEQUENCE[:n]:
        out.append(raw.replace("[[END_LESSON]]", "").strip())
    return out
