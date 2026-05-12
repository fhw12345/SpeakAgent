"""Playwright E2E tests for the course-list homepage flow.

Reuses the `server` fixture (real uvicorn subprocess) from test_browser_smoke.py.
"""
from pathlib import Path

SCREENSHOTS = Path(__file__).resolve().parent / "screenshots"


def test_list_renders_56_rows(server, page):
    page.goto(f"http://127.0.0.1:{server}/")
    page.wait_for_selector("#list-view .lesson-row")
    rows = page.locator("#list-view .lesson-row")
    assert rows.count() == 56, f"expected 56 rows, got {rows.count()}"
    # First row should be W1D1; last should be W8D7.
    first = rows.nth(0)
    last = rows.nth(55)
    assert first.get_attribute("data-id") == "W1D1"
    assert last.get_attribute("data-id") == "W8D7"
    page.screenshot(path=str(SCREENSHOTS / "course_list.png"))


def test_click_w1d1_opens_dialogue_view(server, page):
    page.goto(f"http://127.0.0.1:{server}/")
    page.wait_for_selector("#list-view .lesson-row")
    # Dialogue view starts hidden, list visible.
    assert page.locator("#dialogue-view").is_hidden()
    assert page.locator("#list-view").is_visible()

    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")
    assert page.locator("#dialogue-view").is_visible()
    assert page.locator("#list-view").is_hidden()
    assert page.locator("#start-btn").count() == 1


def test_click_unavailable_shows_coming_soon_and_stays(server, page):
    page.goto(f"http://127.0.0.1:{server}/")
    page.wait_for_selector("#list-view .lesson-row")
    page.click('.lesson-row[data-id="W1D2"]')
    # Stays on list.
    assert page.locator("#list-view").is_visible()
    assert page.locator("#dialogue-view").is_hidden()
    # Notice shown.
    page.wait_for_selector("#list-notice:not([hidden])")
    notice = page.text_content("#list-notice")
    assert notice and "Coming soon" in notice


def test_session_end_returns_to_list_and_highlights_next(server, page):
    page.goto(f"http://127.0.0.1:{server}/")
    page.wait_for_selector("#list-view .lesson-row")
    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")
    # Simulate the dialogue view firing session_end for W1D1 (order=1).
    page.evaluate(
        "window.dispatchEvent(new CustomEvent('session_end', {detail: {lessonId: 'W1D1', order: 1}}))"
    )
    page.wait_for_selector("#list-view:not([hidden])")
    assert page.locator("#dialogue-view").is_hidden()
    # Next row (order=2 -> W1D2) gets .next-lesson class.
    next_row = page.locator(".lesson-row.next-lesson")
    assert next_row.count() == 1
    assert next_row.first.get_attribute("data-id") == "W1D2"


def test_session_end_wraps_for_last_lesson(server, page):
    page.goto(f"http://127.0.0.1:{server}/")
    page.wait_for_selector("#list-view .lesson-row")
    # Open W1D1 then simulate session_end as if order=56 finished.
    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")
    page.evaluate(
        "window.dispatchEvent(new CustomEvent('session_end', {detail: {lessonId: 'W8D7', order: 56}}))"
    )
    page.wait_for_selector("#list-view:not([hidden])")
    next_row = page.locator(".lesson-row.next-lesson")
    assert next_row.count() == 1
    assert next_row.first.get_attribute("data-id") == "W1D1"
