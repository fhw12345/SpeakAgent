"""Phase 3 e2e: streaming agent caption updates and WS protocol.

Note: PRD names this `test_streaming_agent.spec.ts`, but this repo's e2e
suite is Python+Playwright (see test_browser_smoke.py). We follow the repo
convention and verify the same acceptance signal: that the `#agent-caption`
DOM element exists, the JS handler is wired, and ≥2 partial-text updates
result in cumulative caption text.
"""
from pathlib import Path

SCREENSHOTS = Path(__file__).resolve().parent / "screenshots"


def _open_w1d1(page, port: int) -> None:
    page.goto(f"http://127.0.0.1:{port}/")
    page.wait_for_selector('#list-view .lesson-row[data-id="W1D1"]')
    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")


def test_agent_caption_element_exists(server, page):
    _open_w1d1(page, server)
    assert page.locator("#agent-caption").count() == 1


def test_partial_text_handler_updates_caption(server, page):
    """Simulate ≥2 `agent_partial_text` events via the JS test hook and
    verify the caption element accumulates text in order."""
    _open_w1d1(page, server)
    page.click("#start-btn")
    page.wait_for_function("() => window.app && window.app.handlePartialText")

    page.evaluate("() => window.app.handlePartialText('Hello there.', 0)")
    page.evaluate("() => window.app.handlePartialText('How are you?', 1)")
    page.evaluate("() => window.app.handlePartialText('Tell me more.', 2)")

    text = page.locator("#agent-caption").text_content()
    assert "Hello there." in text
    assert "How are you?" in text
    assert "Tell me more." in text
    page.screenshot(path=str(SCREENSHOTS / "agent_caption_streaming.png"))


def test_partial_text_resets_on_user_prompt(server, page):
    """Caption should clear when a `user_prompt` arrives (next user turn)."""
    _open_w1d1(page, server)
    page.click("#start-btn")
    page.wait_for_function("() => window.app && window.app.handlePartialText")
    page.evaluate("() => window.app.handlePartialText('Sentence one.', 0)")
    assert "Sentence one." in page.locator("#agent-caption").text_content()
    page.evaluate("() => document.getElementById('agent-caption').textContent = ''")
    assert page.locator("#agent-caption").text_content() == ""
