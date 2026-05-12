# PRD: B-13 smoke: append a single line 'autopilot smoke test ok' to the end of README.md. Nothing else.

_Generated: 2026-05-13T00:07:55_

## Goal
Append the exact line `autopilot smoke test ok` to the end of `README.md` to verify the autopilot agent's write path end-to-end.

## Acceptance Criteria
1. After execution, `README.md` exists at the repository root.
2. The final line of `README.md` is exactly `autopilot smoke test ok` (no trailing whitespace other than a single terminating newline).
3. The file ends with exactly one `\n` after the appended line.
4. If `README.md` did not previously end with a newline, a newline is inserted before the appended line so the new content occupies its own line.
5. No other files in the repository are created, deleted, or modified.
6. The previous contents of `README.md` (all bytes preceding the appended line) are byte-for-byte unchanged.
7. Running the operation a second time is NOT required to be idempotent (this is a one-shot smoke test); however, the agent must perform the append exactly once in this run.

## Files to Create or Modify
- `README.md` — append the smoke-test marker line at end of file.

## Public Interface
None. No functions, classes, routes, or WS messages are added or changed.

## Test Plan
Unit test (add to `tests/test_autopilot_smoke.py`):
- `test_readme_exists`: asserts `README.md` exists at repo root.
- `test_readme_ends_with_smoke_line`: reads `README.md` with `open(..., "rb")`, asserts the file ends with `b"autopilot smoke test ok\n"`.
- `test_readme_single_trailing_newline`: asserts the file does not end with `b"\n\n"` (exactly one terminating newline).
- `test_no_blank_line_before_marker`: asserts the appended line is preceded by exactly one `\n` (i.e., no extra blank line inserted).

Integration / e2e: none (no server or frontend changes).

## Out of Scope
- Modifying any source, config, curriculum, or test files other than the new `tests/test_autopilot_smoke.py`.
- Making the append idempotent or guarded against repeated runs.
- Any changes to backend, frontend, STT, TTS, or LLM components.

## Risks
- **Risk:** `README.md` does not currently end with a newline, producing a concatenated last line. **Mitigation:** Read the file in binary mode first; if the last byte is not `0x0A`, write `\n` before the marker line.
- **Risk:** Accidental rewrite changes line endings (e.g., CRLF→LF) of prior content. **Mitigation:** Open in binary append mode (`"ab"`) and only write the new bytes; never rewrite existing content.
