"""Deterministic mock LLM helpers for e2e tests.

The mock state lives inside `server.llm_client` (see `_DEFAULT_MOCK_TEMPLATES`).
When `LLM_MOCK=1` is set in the server process, every call to
`llm_client.generate(...)` returns the next templated reply, cycling through
a fixed list — guaranteeing distinct utterances across turns without
requiring cross-process queue injection.
"""

DEFAULT_MOCK_REPLIES = [
    "Sure — tell me more about that.",
    "Nice. Can you use the word 'tool' in a sentence?",
    "Good. Now describe an API you've used.",
    "Great answer. What does the function return?",
    "Got it. Let's try one more — what's a parameter?",
    "Excellent. We've covered the basics today.",
]
