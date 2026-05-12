# PRD: Phase 1: replace homepage with course list view. Backend adds GET /api/lessons returning 56 lesson stubs. Frontend has list view (default) and dialogue view. Click lesson row to open dialogue. session_end returns to list and highlights next. Only W1D1 has YAML; others render as 'coming soon'. Playwright e2e covers list rendering, click navigation, return-to-list flow.

_Generated: 2026-05-13T00:30:48_

## Goal
Replace the single-lesson homepage with a 56-lesson course list view that navigates into the existing dialogue view on click, and returns to the list (highlighting the next lesson) when a session ends.

## Acceptance Criteria
1. `GET /api/lessons` returns HTTP 200 with JSON `{"lessons": [...]}` containing exactly 56 entries.
2. Each lesson object has fields: `id` (e.g. `"W1D1"`), `week` (int 1–8), `day` (int 1–7), `title` (string), `available` (bool), `order` (int 1–56).
3. Only `W1D1` has `available: true`; the other 55 have `available: false`.
4. `W1D1.title` is loaded from `curriculum/W1D1.yaml`'s `title` field; unavailable lessons use title `"Coming soon"`.
5. Loading `/` shows the list view by default with 56 rows rendered in order, each showing `W{n}D{m} — {title}`.
6. Clicking an available row hides the list and shows the dialogue view for that lesson; clicking an unavailable row shows an inline `"Coming soon"` notice and does not navigate.
7. When the dialogue emits a `session_end` event, the UI returns to the list view and applies CSS class `next-lesson` to the row immediately following the just-finished lesson (wraps to first if last).
8. If the just-finished lesson is the last available one, the next unavailable row receives `next-lesson` highlight.
9. All new/modified Python code passes `pytest`; Playwright e2e tests pass headless.

## Files to Create or Modify
- `server/routes/lessons.py` — new FastAPI router exposing `GET /api/lessons`.
- `server/lesson_catalog.py` — new module building the 56-lesson catalog from `curriculum/`.
- `server/app.py` — register `lessons.router`.
- `web/index.html` — add `<section id="list-view">` and keep `<section id="dialogue-view" hidden>`.
- `web/js/list_view.js` — new: fetch `/api/lessons`, render rows, dispatch click events.
- `web/js/app.js` — view switching logic; listens for `lesson:open` and `session_end`.
- `web/css/list.css` — styles for `.lesson-row`, `.lesson-row.unavailable`, `.lesson-row.next-lesson`.
- `tests/test_lessons_api.py` — backend unit/integration tests.
- `tests/e2e/test_course_list.spec.ts` — Playwright e2e.
- `tests/e2e/playwright.config.ts` — add spec if not auto-discovered.

## Public Interface
**REST**
- `GET /api/lessons` → `200 {"lessons": [{"id": "W1D1", "week": 1, "day": 1, "title": "...", "available": true, "order": 1}, ...]}`

**Python**
- `server/lesson_catalog.py::build_catalog() -> list[dict]` — returns 56 lesson dicts.
- `server/lesson_catalog.py::load_lesson_title(lesson_id: str) -> str | None` — reads `curriculum/{id}.yaml`.

**JS / DOM events**
- `window.dispatchEvent(new CustomEvent('lesson:open', {detail: {id, order}}))` — from list row click.
- `window.dispatchEvent(new CustomEvent('session_end', {detail: {lessonId, order}}))` — from dialogue view at session end.
- `web/js/list_view.js::renderList(lessons, nextOrder?)` exported.
- `web/js/app.js::showList(nextOrder?)` and `showDialogue(lessonId)` exported.

## Test Plan
**Backend unit/integration (`tests/test_lessons_api.py`)**
- `test_get_lessons_returns_56`: status 200, length 56.
- `test_lesson_ids_format`: ids match `W{1-8}D{1-7}` covering all combinations exactly once.
- `test_only_w1d1_available`: exactly one lesson has `available=True` and its id is `W1D1`.
- `test_w1d1_title_from_yaml`: title equals value parsed from `curriculum/W1D1.yaml`.
- `test_unavailable_titles_are_coming_soon`: all 55 unavailable lessons have title `"Coming soon"`.
- `test_order_field_sequential`: `order` is 1..56 matching list index.

**Frontend Playwright e2e (`tests/e2e/test_course_list.spec.ts`)**
- `renders 56 lesson rows on load`.
- `clicking W1D1 opens dialogue view and hides list`.
- `clicking an unavailable row shows "Coming soon" and stays on list`.
- `session_end returns to list and highlights W1D2 with class next-lesson` (simulate via `window.dispatchEvent`).
- `dialogue view is hidden when list view is visible after return`.

## Out of Scope
- Lesson progress persistence across reloads.
- Authoring YAML for lessons beyond W1D1.
- Reordering, filtering, or search UI.

## Risks
- **YAML title key absent or schema drift** — mitigation: `load_lesson_title` falls back to `"Lesson W1D1"` and logs a warning.
- **Dialogue view not currently emitting `session_end`** — mitigation: add a single `window.dispatchEvent(new CustomEvent('session_end', ...))` call in the existing dialogue completion handler in `web/js/app.js`.
- **Playwright not yet configured in repo** — mitigation: include minimal `playwright.config.ts` and document `npx playwright install` in the test file header comment.
