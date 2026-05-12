"""Playwright e2e: realtime lesson W1D2 with mocked LLM.

PRD names this file `realtime_lesson.spec.ts`, but the project's e2e runner
is pytest+playwright (Python), not a JS Playwright runner. This Python module
fulfils the same acceptance criterion (3 mocked user turns, 3 distinct
agent utterances render in the transcript pane).
"""
from pathlib import Path

SCREENSHOTS = Path(__file__).resolve().parent / "screenshots"


def _open_w1d2(page, port: int) -> None:
    page.goto(f"http://127.0.0.1:{port}/")
    page.wait_for_selector('#list-view .lesson-row[data-id="W1D2"]')
    page.click('.lesson-row[data-id="W1D2"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")


def test_realtime_lesson_three_turns(realtime_server, page):
    _open_w1d2(page, realtime_server)
    page.click("#start-btn")
    # First agent utterance arrives from /api/lesson/start.
    page.wait_for_selector("#dialogue .agent", timeout=15000)
    page.wait_for_selector("#realtime-controls:not([hidden])")

    for i, msg in enumerate([
        "I use grep every day.",
        "An API returns JSON data.",
        "We pass arguments to the function.",
    ]):
        page.fill("#realtime-input", msg)
        page.click("#realtime-send")
        # Wait until we have (i + 2) agent turns rendered (1 initial + i+1 replies).
        page.wait_for_function(
            f"document.querySelectorAll('#dialogue .agent').length >= {i + 2}",
            timeout=15000,
        )

    captions = page.locator("#dialogue .agent").all_text_contents()
    assert len(captions) >= 4, f"expected >=4 agent turns, got {len(captions)}: {captions!r}"
    user_turns = page.locator("#dialogue .user").all_text_contents()
    assert len(user_turns) == 3
    # All four agent utterances must be distinct.
    cleaned = [c.strip() for c in captions[:4]]
    assert len(set(cleaned)) == 4, f"agent utterances not distinct: {cleaned!r}"
    # The session must NOT be done yet (only 3 of 6 user turns used).
    status = page.text_content("#status")
    assert status and "complete" not in status.lower(), f"unexpected status: {status!r}"
    page.screenshot(path=str(SCREENSHOTS / "realtime_w1d2.png"))
