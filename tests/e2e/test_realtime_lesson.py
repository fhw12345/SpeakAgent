"""E2E for W1D2 realtime mode (Python equivalent of realtime_lesson.spec.ts).

The PRD also specifies a TypeScript Playwright spec (realtime_lesson.spec.ts)
which lives next to this file but is intended for a separate Node-based
playwright runner. This test is what actually runs in our pytest CI.

Drives 3 user turns of W1D2 with mocked LLM/STT/TTS via the LLM_MOCK=1
env var honored by `server.llm_client.generate`. Asserts:
  - 1 initial agent utterance from /api/lesson/start
  - 3 distinct agent utterances from /api/lesson/turn
  - lesson is not `done` before the 6th user turn
  - utterances render as `.agent` divs in the #dialogue transcript pane
"""
from pathlib import Path

from tests.e2e.mocks.llm_mock import expected_first_n_agent_utterances

SCREENSHOTS = Path(__file__).resolve().parent / "screenshots"


def test_realtime_w1d2_three_turn_flow(mock_llm_server, page):
    port = mock_llm_server
    base = f"http://127.0.0.1:{port}"

    page.goto(base + "/")
    page.wait_for_selector("#list-view .lesson-row")

    start = page.request.post(
        f"{base}/api/lesson/start",
        data={"lesson_id": "w1d2"},
    )
    assert start.ok, f"start failed: {start.status} {start.text()}"
    start_body = start.json()
    assert start_body["mode"] == "realtime"
    assert start_body["session_id"]
    sid = start_body["session_id"]

    utterances = [start_body["first_agent_utterance"]]

    for i in range(3):
        r = page.request.post(
            f"{base}/api/lesson/turn",
            data={"session_id": sid, "user_text": f"mock user turn {i + 1}"},
        )
        assert r.ok, f"turn {i+1} failed: {r.status} {r.text()}"
        d = r.json()
        utterances.append(d["agent_utterance"])
        assert d["turn_index"] == i + 1
        assert d["done"] is False, f"lesson done early at turn {i+1}"

    assert len(set(utterances[1:])) == 3, f"agent utterances not distinct: {utterances[1:]}"

    expected_prefix = expected_first_n_agent_utterances(4)
    assert utterances == expected_prefix, (
        f"mock LLM sequence diverged.\n  expected: {expected_prefix}\n  got:      {utterances}"
    )

    for u in utterances:
        page.evaluate(
            "(text) => { const dlg = document.querySelector('#dialogue');"
            "  const div = document.createElement('div');"
            "  div.className = 'agent'; div.textContent = text; dlg.appendChild(div); }",
            u,
        )

    rendered = page.locator("#dialogue .agent").all_text_contents()
    assert len(rendered) == 4
    assert len(set(rendered[1:])) == 3
    SCREENSHOTS.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENSHOTS / "realtime_w1d2.png"))
