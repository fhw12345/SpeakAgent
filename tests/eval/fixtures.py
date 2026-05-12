# tests/eval/fixtures.py
"""Golden fixtures for scorer regression. Add new ones freely; don't reorder existing."""

def _w(words):
    return [{"w": w, "start": i * 0.4, "end": i * 0.4 + 0.3, "prob": 0.95} for i, w in enumerate(words)]


FIXTURES = [
    {
        "id": "perfect_match",
        "user_text": "hello and welcome",
        "ideal": "hello and welcome",
        "confidence": 0.95,
        "words": _w(["hello", "and", "welcome"]),
        "fake_judge": '{"content_score": 5, "rewrite": "Hello and welcome.", "issues": []}',
        "pron_range": (0.9, 1.0),
        "expected_content_score": 5,
    },
    {
        "id": "one_word_off",
        "user_text": "hello and welcom",
        "ideal": "hello and welcome",
        "confidence": 0.85,
        "words": _w(["hello", "and", "welcom"]),
        "fake_judge": '{"content_score": 4, "rewrite": "Hello and welcome.", "issues": ["welcom -> welcome"]}',
        "pron_range": (0.5, 0.95),
        "expected_content_score": 4,
    },
    {
        "id": "lots_of_fillers",
        "user_text": "um i think uh yes",
        "ideal": "yes",
        "confidence": 0.80,
        "words": _w(["um", "i", "think", "uh", "yes"]),
        "fake_judge": '{"content_score": 2, "rewrite": "Yes.", "issues": ["fillers"]}',
        "pron_range": (0.0, 0.6),
        "expected_content_score": 2,
    },
    {
        "id": "empty_audio",
        "user_text": "",
        "ideal": "anything",
        "confidence": 0.0,
        "words": [],
        "fake_judge": '{"content_score": 1, "rewrite": "(no answer)", "issues": ["silent"]}',
        "pron_range": (0.0, 0.05),
        "expected_content_score": 1,
    },
    {
        "id": "long_correct_answer",
        "user_text": "the agent loop takes an observation chooses a tool and acts",
        "ideal": "the agent loop takes an observation chooses a tool and acts",
        "confidence": 0.92,
        "words": _w(["the", "agent", "loop", "takes", "an", "observation", "chooses", "a", "tool", "and", "acts"]),
        "fake_judge": '{"content_score": 5, "rewrite": "The agent loop observes, chooses a tool, and acts.", "issues": []}',
        "pron_range": (0.85, 1.0),
        "expected_content_score": 5,
    },
    {
        "id": "broken_judge_json_falls_back_to_3",
        "user_text": "some answer",
        "ideal": "some answer",
        "confidence": 0.9,
        "words": _w(["some", "answer"]),
        "fake_judge": "this is not json at all",
        "pron_range": (0.85, 1.0),
        "expected_content_score": 3,
    },
]
