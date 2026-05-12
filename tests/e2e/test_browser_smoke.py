"""Real browser E2E tests using Playwright.

These tests start a real uvicorn server and drive a real Chromium browser
against it. They need the AZURE_SPEECH_KEY+REGION env vars to actually
hear voice (otherwise TTS falls back to edge-tts which may 403). For
checking message protocol / UI rendering, the env vars are not required.

Run separately from the rest:
    pytest tests/e2e/ -v
or:
    pytest -v --no-header  (will skip e2e if chromium not installed)
"""
from pathlib import Path

SCREENSHOTS = Path(__file__).resolve().parent / "screenshots"


def _open_w1d1(page, port: int) -> None:
    page.goto(f"http://127.0.0.1:{port}/")
    page.wait_for_selector('#list-view .lesson-row[data-id="W1D1"]')
    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector("#dialogue-view:not([hidden])")


def test_homepage_renders(server, page):
    """Smoke: homepage loads with the course list view visible."""
    page.goto(f"http://127.0.0.1:{server}/")
    page.wait_for_selector("#list-view .lesson-row")
    rows = page.locator("#list-view .lesson-row")
    assert rows.count() == 56
    page.screenshot(path=str(SCREENSHOTS / "homepage.png"))


def test_dialogue_pane_exists(server, page):
    """After opening W1D1, the dialogue/controls/scorecard/dev-panel sections render."""
    _open_w1d1(page, server)
    for sel in ["#dialogue", "#start-btn", "#ptt-btn", "#status",
                "#scorecard", "#dev-panel"]:
        assert page.locator(sel).count() == 1, f"missing element {sel}"


def test_session_starts_and_first_caption_appears(server, page):
    """Open W1D1, click Start, wait for first agent caption div."""
    _open_w1d1(page, server)
    page.click("#start-btn")
    page.wait_for_selector("#dialogue .agent", timeout=15000)
    captions = page.locator("#dialogue .agent").all_text_contents()
    assert len(captions) >= 1, "no agent caption appeared"
    assert "Coach:" in captions[0], f"unexpected caption: {captions[0]!r}"
    page.screenshot(path=str(SCREENSHOTS / "first_caption.png"))


def test_translation_and_gloss_render_for_first_glossed_turn(server, page):
    """W1D1 turn 3 has gloss; verify .translation + .gloss elements render."""
    _open_w1d1(page, server)
    page.click("#start-btn")
    page.wait_for_selector("#dialogue .gloss", timeout=30000)
    gloss_texts = page.locator("#dialogue .gloss").all_text_contents()
    translations = page.locator("#dialogue .translation").all_text_contents()
    assert len(gloss_texts) >= 1, "no gloss element rendered"
    assert len(translations) >= 1, "no translation element rendered"
    sample = gloss_texts[0]
    assert "/" in sample or any("一" <= c <= "鿿" for c in sample), \
        f"gloss looks empty: {sample!r}"
    page.screenshot(path=str(SCREENSHOTS / "gloss_visible.png"))
