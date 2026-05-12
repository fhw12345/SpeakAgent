# speakAgent — Design Spec

**Date:** 2026-05-12
**Owner:** fhw12345
**Status:** Draft for review

---

## 1. Goal & Non-Goals

### Goal
Build a local web-based English speaking & listening trainer that, in **8 weeks at 30–45 min/day**, takes the user from "can read tech docs but freezes when speaking, can't follow native-speed audio" (CEFR ~A2) to **able to handle a full English-language interview for an AI Agent engineering role** with reasonable confidence (target ~B1+).

Realistic outcomes after 8 weeks (~30–40 hours of training):
- Understand ~85% of standard interview questions including moderate accents.
- Answer behavioral and project-explanation questions without rigid templates.
- Talk through one of the user's own AI/Agent projects end-to-end with mid-depth follow-ups.
- Survive system-design discussions verbally (with some hesitation).
- "Truly fluent" is **not** in scope — the goal is "interview-survivable" with a clear quality bar.

### Non-Goals
- Multi-user accounts, cloud deployment, mobile apps.
- Per-phoneme pronunciation scoring.
- Paid TTS providers (edge-tts is sufficient).
- Building a general-purpose language tutor — every design choice serves the AI Agent interview goal.
- Replacing human practice partners — this is a high-volume drill tool, not a conversation partner.

---

## 2. Acceptance Criteria

The system is acceptable when **all** of the following hold:

1. **End-to-end loop works**: user opens `localhost:8765`, picks today's lesson, speaks into mic, sees live captions, hears TTS reply, gets a scorecard at the end. Round-trip latency ≤ 3s for short utterances on user's machine.
2. **8-week curriculum is fully populated** with at least one runnable lesson per day (56 lessons), each driven by a YAML/JSON lesson plan that the coach can execute without code changes.
3. **Personal-project integration**: at least 5 of the user's own repos under `D:/repo/` (FundAgent, Nexis, NBAVedio, vs-debugger-mcp, Agent Maestro) appear as practice material with project-specific interview questions.
4. **Autopilot runs continuously** with token budget enforcement, never touches `main` directly, escalates correctly on policy violations, and has produced ≥ 1 self-generated improvement merged via human review during a 1-week burn-in.
5. **Eval suite passes**: scorer regression tests (≥ 20 fixtures) all green; LLM/STT/TTS fallback paths each exercised by an integration test.
6. **Harness quality bar**: structured logs per session, hot-reload of curriculum, dev panel exposes recent LLM calls + token spend + latencies, kill switch (`autopilot/PAUSE`) works.

---

## 3. Architecture

```
Browser (web/)
  │  WebSocket: bidirectional audio frames + control messages
  ▼
FastAPI server (server/main.py)
  ├─ session_manager     one SpeechSession per browser tab
  ├─ coach (orchestration) ──▶ drives dialogue from today's lesson plan
  │     ├─ stt   (faster-whisper, local)
  │     ├─ llm   (urllib + factory + 3-retry, copied from NBAVedio)
  │     ├─ tts   (edge-tts, streaming)
  │     └─ scorer (LLM-judge + WER + fluency metrics)
  └─ storage  (JSON files for sessions, SQLite for SRS vocab queue)

autopilot/ (separate long-running process)
  └─ loop.py  ──▶ Discovery → Pick → Spawn `claude -p` → Verify → Commit (branch only)
```

**Why this split:** every layer has one responsibility and a swappable interface. `coach.py` is the only module that knows the curriculum. `llm.py` / `stt.py` / `tts.py` are dumb adapters. UI is dumb too — it streams audio and renders whatever the server sends.

---

## 4. Module Inventory

### `server/llm.py`
- Mirror NBAVedio pattern: factory `get_assistant(backend: "claude"|"gpt", logger)` returns object with `_call(prompt, system) -> str`.
- HTTP client: bare `urllib.request` (no `anthropic`/`openai` SDK).
- Default backend: Claude via `http://localhost:23333/api/anthropic/v1/messages` (Agent Maestro local gateway). Env var `CLAUDE_API_ENDPOINT` overrides.
- Model: `claude-opus-4.7-1m-internal` (default), configurable.
- Retry: 3 attempts with exponential backoff (10s, 20s, 30s), structured-logged.
- Add (vs NBAVedio): optional `stream=True` so TTS can begin playback before full LLM response arrives.
- Fallback: if Claude fails 3×, automatically route to `gpt` backend; if both fail, return a graceful spoken error in-session and log incident for autopilot.

### `server/stt.py`
- `faster-whisper` with `small` model by default (CPU-friendly), `medium` if GPU detected.
- VAD-based segmentation (built into faster-whisper).
- Long-running worker process started at server boot (avoid cold-start per utterance).
- Input: 16kHz mono PCM frames over WebSocket. Output: `{text, confidence, words: [{w, start, end, prob}]}`.

### `server/tts.py`
- `edge-tts` async streaming.
- Voices, used to expose the user to the four accents most common in remote AI Agent interviews:
  - `en-US-AriaNeural` (US female, default), `en-US-GuyNeural` (US male)
  - `en-GB-RyanNeural` (UK male), `en-GB-SoniaNeural` (UK female)
  - `en-IN-NeerjaNeural` (Indian female), `en-IN-PrabhatNeural` (Indian male)
  - `zh-CN-XiaoxiaoNeural` configured to speak English (Chinese-accented English; used sparingly to simulate domestic interviewers speaking English)
- Accent rotation rules:
  - Weeks 1–2 (listening foundation): US-only, build comprehension before adding accent stress.
  - Weeks 3–4 (shadowing): US 70% / UK 30%.
  - Weeks 5–6 (topic speaking): US 50% / UK 25% / Indian 15% / Chinese-accented 10%.
  - Weeks 7–8 (mock interviews): random rotation across all four; each mock interview holds one accent throughout for realism. Coach records which accents the user struggles with most and biases SRS toward those clips.
- Output: streamed MP3 chunks pushed over WebSocket as they arrive.
- Fallback: if edge-tts unreachable, server signals client to use browser-native `speechSynthesis` API.

### `server/coach.py`
- State machine: `Idle → SpeakPrompt → ListenUser → Score → NextTurn → … → SessionEnd`.
- Loads a `LessonPlan` (YAML or JSON) and executes its `turns[]` array.
- Each turn declares: speaker (agent/user), prompt template, expected response shape, scoring rubric pointer, optional follow-up branch.
- Hot-reload: re-reads lesson file at the start of every new session.
- Knows nothing about HTTP — pure orchestration; talks to adapters via interfaces.

### `server/scorer.py`
Three independent dimensions, computed in parallel after each user turn:
1. **Pronunciation proxy** — STT confidence + WER vs an LLM-rephrased "ideal" version of the same idea. (We don't do real phoneme alignment; this is a pragmatic proxy.)
2. **Fluency** — words per minute, count of pauses > 800ms, count of filler words ("um", "uh", "like").
3. **Content** — LLM judge gives 1–5 score on relevance, technical accuracy, and grammar; also produces a "more idiomatic rewrite" of the user's answer.
Outputs merged into a single `TurnScore` JSON.

### `server/progress.py`
- Append-only session log → `data/sessions/<date>-<lesson_id>.json`.
- Hard words extracted by scorer go into SQLite SRS queue (table `vocab_srs`: `word, first_seen_at, next_review_at, interval_days, ease`).
- SM-2 algorithm for SRS scheduling (well-trodden, simple).
- Daily summary: streak count, minutes practiced, top 3 weak areas.

### `server/main.py`
- FastAPI app, mounts `web/` as static, exposes `/ws` for the audio session, `/api/today` for lesson selection, `/api/progress` for the dashboard, `/dev` for the debug panel.

### `web/`
- Single-page vanilla HTML + one `app.js` + one `style.css`. No build tools.
- Components: lesson picker, live-caption pane, dialogue history, push-to-talk button (spacebar hold), waveform indicator, scorecard panel, progress dashboard, dev panel.
- Mobile-friendly via responsive CSS (so the user can practice on phone over LAN).

---

## 5. Harness Engineering

This section is investment-heavy because the user explicitly asked for it. Strong harness pays compound interest over the 8 weeks.

- **Single config surface**: `server/config.py` + `.env`. Every endpoint, key, model name, voice, curriculum path lives here. No magic constants in business logic.
- **Structured logging**: `structlog` JSON output; one log file per session under `data/logs/<date>/<session_id>.jsonl`. Every LLM call, STT call, TTS call, scorer call is logged with latency and token counts.
- **Error recovery ladder**:
  - LLM: Claude → GPT → graceful spoken error.
  - STT: retry once → ask user to re-record → log for autopilot.
  - TTS: edge-tts → browser-native speechSynthesis.
- **Observability**: `/dev` panel (browser) shows current session state, last 10 LLM calls (prompt + response truncated), token spend today, p50/p95 latencies for each adapter.
- **Hot-reload**: curriculum files re-read on each new session; prompt templates re-read on each LLM call (cheap) — so iteration is instant, no server restart.
- **Eval suite**: `tests/eval/` runs ~20 fixtures asserting scorer behavior ("if user answer is X, score should be in range Y"). Run on every commit and before every autopilot merge.
- **Replay**: every session's audio + transcript archived to `data/sessions/<id>/` so the user can re-listen ("how did I mispronounce that yesterday?"). Web UI exposes a replay view.
- **Kill switch**: presence of `autopilot/PAUSE` file halts autopilot within ≤ 60s.

---

## 6. Data Flow — Mock Interview Example

1. Browser connects → server creates `SpeechSession`, loads today's `LessonPlan` (e.g. *Mock Interview #3 — System Design: Build a RAG Agent*).
2. Coach renders the first prompt template → calls LLM → calls TTS → streams audio + caption text to browser.
3. Browser plays audio; UI flips to "recording" state. User holds spacebar, speaks, releases.
4. Audio frames stream to server → STT → text + word-level timing.
5. Coach appends to dialogue history → calls LLM (with system prompt = interviewer persona + project context if applicable) → next turn.
6. In parallel: scorer runs on the user's last turn → result stored in session, displayed inline.
7. After N turns or time limit → coach ends session → progress.py writes summary, hard words → SRS, streak update.
8. Browser shows scorecard: per-dimension scores, top 3 issues, recommended idiomatic rewrites, words added to tomorrow's review.

---

## 7. 8-Week Curriculum

| Week | Theme | Daily 30-min split |
|---|---|---|
| 1–2 | **Listening foundation** — AI/tech English ear training | 5min SRS review · 20min intensive listening (curated tech-talk clips, sentence-by-sentence STT comparison) · 5min summary recall |
| 3–4 | **Shadowing** — build oral muscle memory | 5min SRS · 20min shadowing (agent reads → user repeats → WER + fluency feedback) · 5min free recall |
| 5–6 | **Topic speaking** — explain one thing in 1 minute | 5min SRS · 20min topic cards ("Explain RAG", "Why debate over ensemble?", drawn from personal projects 50% of the time) · AI follow-ups · 5min idiomatic rewrite review |
| 7–8 | **Full mock interviews** — one complete session per day | Behavioral + project deep-dive + system-design-verbal. End-of-session detailed review. |

Each lesson is a YAML/JSON file under `curriculum/<week>/<day>-<topic>.yml`. The coach is curriculum-driven: adding lessons requires no code change.

---

## 8. Question Bank & Source Material

- **Interview bank**: `data/interview_bank.json` — ~80 hand-curated questions for AI Agent roles, tagged by category (behavioral 30, LLM/Agent technical 30, system-design 20), each with difficulty, keywords, and a model-answer outline.
- **Listening clips**: `data/listening/` — short clips from public technical talks (Karpathy, Lex Fridman segments), referenced by URL with a download script; not redistributed.
- **Vocabulary**: ~500 high-frequency AI/interview terms pre-seeded into the SRS queue.
- **Personal-project material**: `data/personal_projects.json` — see § 10.

---

## 9. Autopilot — Continuous Self-Improvement

The user opted into **continuous (24/7) autopilot** via repo-local `CLAUDE.md`. The autopilot subsystem runs as a separate long-running Python process that orchestrates Claude Code in headless mode (`claude -p ...`).

### 9.1 Loop

`Discovery → Backlog → Pick → Spawn → Verify → Commit (branch) → PR-ready note → repeat`

1. **Discovery triggers** (run every loop iteration):
   - `from_test_fails.py` — parse last test run, file new backlog item per failure.
   - `from_session_logs.py` — scan recent user sessions; cluster repeated low scores or stuck patterns; if same issue appears in **≥ 3 sessions**, file backlog item.
   - `from_eval_drift.py` — compare current eval-suite scores vs last week's baseline; regression > 5% → backlog item with `priority=high`.
   - `from_repo_scan.py` — once per day, scan `D:/repo/*/README.md` and recent commits across user's other repos; surface candidates to refresh `personal_projects.json` (proposed as escalation, not auto-applied).
2. **Pick**: highest-priority unblocked in-scope item. Skip anything tagged `needs-human`.
3. **Spawn**: launch `claude -p "<prompt-from-backlog-item>"` in a fresh worktree under `.claude/worktrees/autopilot-<date>-<slug>`.
4. **Verify**: child agent must (a) run full eval suite, (b) run integration tests, (c) self-review with `superpowers:requesting-code-review`. If any fails, the worktree is preserved, a `needs-human` note added, item moves to inbox.
5. **Commit**: only ever to branch `autopilot/<date>-<topic>`. Commit prefix `[auto]`. Never to `main`. PR creation is left to the human.

### 9.2 Safety Guardrails (HARD constraints)

- **Rate limit (anti-runaway only, NOT budget)**: `autopilot/policies/rate_limit.yml` caps LLM call rate (default 60 req/min) to prevent a stuck loop from hammering the gateway. Token cost is a non-concern. If the rate cap trips, autopilot pauses for 60s and logs a warning; if it trips 3× in an hour, autopilot escalates ("possible infinite loop").
- **Branch isolation**: `main` is never touched. Even merges happen via human-issued PR.
- **Single-task concurrency**: one PRD in flight at a time on the main code base. Discovery may run in parallel.
- **Escalation triggers** (always file to `autopilot/inbox.md`, never auto-execute):
  - Schema or DB migration.
  - New top-level dependency, or > 3 new transitive deps.
  - File deletions (any), directory renames, license changes.
  - Modifications to `autopilot/` itself.
  - Any change to `server/llm.py` retry/fallback policy (regression risk too high).
  - 3 consecutive failures on the same backlog item.
- **Kill switch**: `touch autopilot/PAUSE` halts the loop within 60s; `rm autopilot/PAUSE` resumes.
- **LLM access**: autopilot uses the same `localhost:23333` Claude gateway as the runtime. No separate paid API key required.
- **Audit trail**: every loop iteration writes a structured log entry under `autopilot/runs/<timestamp>.jsonl` capturing: triggers fired, item picked, prompt sent, exit status, files touched, eval-suite delta.

### 9.3 Burn-in Plan

User has opted out of mandatory per-branch review during burn-in (trusts the guardrails: branch-only commits, eval-suite gate, escalation list, kill switch). Autopilot runs from day 1 with full Spawn enabled. Daily digest is written to `autopilot/runs/digest-<date>.md` summarizing what was attempted, what landed on which branch, and what was escalated; user may skim or ignore. If a regression is later traced to an `[auto]` branch, the user can `touch autopilot/PAUSE` and we add the failure pattern to `policies/escalation.yml`.

---

## 10. Personal-Project Material

The user's other repos are first-class practice material because:
- Real-stakes content > synthetic drills.
- The user will actually be asked about these projects in interviews.
- They span a great range of AI Agent topics (multi-vendor LLM orchestration, MCP, vision, agent frameworks).

### 10.1 Schema

`data/personal_projects.json`:

```json
{
  "id": "fundagent",
  "name": "FundAgent",
  "repo_path": "D:/repo/FundAgent",
  "one_liner": "Multi-vendor LLM debate for Chinese mutual fund analysis.",
  "tech_keywords": ["multi-vendor LLM", "debate architecture", "vision import", "AkShare"],
  "interview_angles": [
    {"type": "behavioral", "q": "Walk me through a project where you combined multiple LLMs."},
    {"type": "technical_deep_dive", "q": "Why debate vs ensemble vs single-model? When does debate hurt?"},
    {"type": "system_design", "q": "How would you scale the debate architecture to 100k users?"},
    {"type": "trade_off", "q": "Cost vs quality — when is debate worth it?"}
  ],
  "hard_words": ["heterogeneous", "consensus", "adjudication", "drawdown"],
  "model_answer_outline": "Problem → why single model insufficient → debate protocol → consensus rule → cost mitigation."
}
```

Initial seed (~7 entries): NBAVedio, FundAgent, Nexis, Agent Maestro, vs-debugger-mcp, cc-plugin, FinancialAgent.

### 10.2 Usage in Curriculum

- Weeks 3–4 shadowing: agent reads each project's 30-second elevator pitch; user shadows until WER < 10%.
- Weeks 5–6 topic speaking: 50% of topic cards drawn from `personal_projects.json` angles; agent asks 2 follow-ups per turn.
- Weeks 7–8 mock interviews: ≥ 50% of mock-interview lessons feature the user's real projects as the "tell me about a project" anchor.
- SRS: `hard_words` from each project automatically seeded into the vocab queue.

### 10.3 Autopilot Coupling

`autopilot/triggers/from_repo_scan.py` runs once per day:
- Reads `README.md` and `git log --since=7.days` for each path in `personal_projects.json`.
- If a project gained a notable feature (heuristic: README diff > 200 chars, or commit messages match keywords like "add", "implement", "support"), drafts a proposed update to `personal_projects.json` with new questions/keywords.
- Files the draft to `autopilot/inbox.md` for human review — never auto-merges, because interview content quality matters too much.

---

## 11. Tech Stack (final)

- Python 3.11+, FastAPI, uvicorn, websockets
- `faster-whisper` (CPU works, GPU optional)
- `edge-tts`
- SQLite (SRS), JSON files (sessions, lessons, personal projects, interview bank)
- Frontend: vanilla HTML + one `app.js` + one `style.css`. No React, no build step.
- Logging: `structlog`
- Reused from NBAVedio: LLM access pattern (urllib + factory + 3-retry); local Claude gateway at `localhost:23333`.

---

## 12. Out of Scope (YAGNI)

- Multi-user accounts, authentication.
- Cloud deployment, Docker for the trainer itself (autopilot may use Docker for sandboxed test runs only).
- Native mobile apps.
- Per-phoneme pronunciation scoring.
- Paid TTS providers.
- Auto-merge from autopilot.
- General-purpose language tutoring (non-AI-Agent topics).

---

## 13. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| 8 weeks × 30 min may still be insufficient for true fluency | Acceptance criteria explicitly target "interview-survivable", not "fluent". Weekly self-assessment catches drift early. |
| Autopilot wastes tokens on low-value changes | Discovery requires ≥ 3 repeated signals before filing; daily budget cap; first-week burn-in with mandatory human review. |
| Autopilot introduces regressions | Branch-only commits, eval-suite gate, single-task concurrency, hard escalation list. |
| Local Whisper too slow on CPU | Default to `small` model; document that `medium` requires GPU; integration test measures latency and warns if > 3s. |
| `localhost:23333` Claude gateway down | LLM fallback to GPT backend; if both down, graceful spoken error and incident logged for autopilot. |
| User's repos change shape; `personal_projects.json` rots | `from_repo_scan.py` daily check files diff to inbox for human review. |
| Edge-tts service changes / blocks | Fallback to browser `speechSynthesis`; voice quality drops but training continues. |

---

## 14. Validation Plan

1. **Unit tests** for adapters (llm/stt/tts/scorer) — happy path + each fallback branch.
2. **Eval suite** for scorer — 20+ fixtures; run on every commit.
3. **Integration test**: scripted full session (synthesized audio in, scorecard out) — runs in CI.
4. **Manual end-to-end**: real user runs week-1 day-1 lesson before declaring v0.1 done.
5. **Autopilot dry-run**: 48-hour observation period in dry-run mode (Discovery + logging only) before enabling Spawn.
6. **Weekly user check-in**: lightweight self-rating against acceptance criteria; misses → backlog item.

---

## 15. Repository Layout (final)

```
speakAgent/
├── CLAUDE.md                    # repo-local: opt-in to autonomous mode + repo-specific test workflow
├── README.md
├── server/
│   ├── main.py
│   ├── config.py
│   ├── llm.py
│   ├── stt.py
│   ├── tts.py
│   ├── coach.py
│   ├── scorer.py
│   └── progress.py
├── web/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── curriculum/
│   ├── week1/  ...  week8/      # daily lesson plans (YAML/JSON)
│   └── prompts/                  # role prompts (interviewer, shadow coach, rewrite tutor)
├── data/
│   ├── interview_bank.json
│   ├── personal_projects.json
│   ├── listening/                # downloaded clips (gitignored)
│   ├── sessions/                 # per-session JSON + audio (gitignored)
│   ├── logs/                     # structured logs (gitignored)
│   └── vocab_srs.sqlite
├── autopilot/
│   ├── CLAUDE.md                 # opt-in declaration + loop boundaries
│   ├── loop.py
│   ├── backlog.md
│   ├── inbox.md
│   ├── policies/rate_limit.yml
│   ├── PAUSE                     # absent by default; touch to halt
│   ├── triggers/
│   │   ├── from_test_fails.py
│   │   ├── from_session_logs.py
│   │   ├── from_eval_drift.py
│   │   └── from_repo_scan.py
│   ├── policies/
│   │   ├── safe_actions.yml
│   │   └── escalation.yml
│   └── runs/                     # per-iteration logs (gitignored)
├── tests/
│   ├── unit/
│   ├── integration/
│   └── eval/
├── docs/
│   └── superpowers/specs/
│       └── 2026-05-12-speakagent-design.md   # this file
├── requirements.txt
└── .env.example
```

---

## 16. Open Questions (none blocking)

- Exact eval-suite size at v1 (currently "≥ 20 fixtures" — refine in implementation plan).
- Specific tech-talk clips for weeks 1–2 listening (curate during implementation, not blocking design).
- Whether to add a lightweight "pronunciation tip" overlay for repeated mispronunciations after week 4 — defer; revisit after burn-in.

---

## 17. Realtime Lesson Mode

### 17.1 Motivation
The original `coach.py` design assumes every lesson is fully scripted: each agent turn is hard-coded in YAML and the coach merely walks the `turns[]` array. Scripted lessons are ideal for tightly-controlled drills (W1D1 listening foundation) but are too rigid for topic-speaking and mock-interview lessons (Weeks 5–8) where the agent must react to whatever the user actually said. Phase 2 of the conversational coach upgrade introduces a second lesson mode where the agent's turns are LLM-generated from lesson context plus running conversation history. Streaming is **not** in scope for this phase (Phase 3).

### 17.2 Two Lesson Modes
Lesson YAML gains a top-level `mode` field with two allowed values:

| Mode | Behavior | Required YAML fields | Source of agent turns |
|---|---|---|---|
| `scripted` (default) | Existing behavior — coach walks `turns[]` | `lesson_id`, `turns[]` (existing schema) | YAML |
| `realtime` | Coach asks the LLM for the next agent utterance after every user turn | `topic`, `target_phrases` (list[str]), `vocabulary` (list[str]), `coach_persona` (str) | LLM |

Rules:
- An absent or invalid `mode` value falls back to `scripted` and emits a `WARN` log so curriculum authors notice.
- Realtime lessons that omit any required field raise `ValueError("realtime lesson missing field: <name>")` at load time — fail fast, before a session starts.
- Scripted lessons remain byte-identical: W1D1 must produce the same agent turn text and the same regression snapshot as before this change.

### 17.3 Loader Changes (`server/lesson_loader.py`)
A new dataclass `LessonSpec` becomes the canonical in-memory representation:

```python
LessonSpec(
    mode: Literal["scripted", "realtime"],
    lesson_id: str,
    topic: str | None,
    target_phrases: list[str],
    vocabulary: list[str],
    coach_persona: str | None,
    turns: list[ScriptedTurn] | None,   # populated only for scripted
)
```

`lesson_loader.load(lesson_id: str) -> LessonSpec` parses the YAML, validates per-mode required fields, and returns a `LessonSpec`. Hot-reload behavior is preserved.

### 17.4 Dispatch (`server/coach.py`)
`coach.py` becomes a thin dispatcher: on session start it inspects `lesson.mode` and hands off to either the existing scripted handler or `coach_realtime`. The two handlers expose the same external contract (REST shape + scoring hooks) so the rest of the system — scorer, progress, `web/` UI — remains mode-agnostic.

### 17.5 Realtime Handler (`server/coach_realtime.py`)
New module. Public surface:

```python
coach_realtime.start_session(lesson: LessonSpec) -> tuple[str, str]
    # returns (session_id, first_agent_utterance)

coach_realtime.handle_turn(session_id: str, user_text: str) -> dict
    # returns {agent_utterance: str, turn_index: int, done: bool}

coach_realtime.MAX_USER_TURNS = 6
coach_realtime.END_SENTINEL  = "[[END_LESSON]]"
```

Behavior:
- `start_session` allocates a session id, builds the system prompt from the lesson, asks the LLM for the opening utterance, and returns it. The opening line is **not** drawn from YAML.
- `handle_turn` appends the user message to history, calls the LLM, appends the agent reply, and returns it. `done` becomes `true` after `MAX_USER_TURNS` user turns or when the LLM emits `END_SENTINEL` (the sentinel is stripped from the user-visible utterance).
- An unknown `session_id` raises `KeyError` — callers (the FastAPI route) translate to HTTP 404.

Session storage: `coach_realtime._SESSIONS: dict[str, SessionState]` with a 30-minute TTL eviction sweep. This keeps Phase 2 process-local and avoids a database migration (which would also trip the autopilot escalation list).

### 17.6 LLM Prompt Construction
`coach_realtime.SYSTEM_TEMPLATE` is a module-level constant assembled from:
- `coach_persona` — voice and instructional stance.
- `topic` — single-line lesson focus.
- `target_phrases` — phrases the user should be guided to produce.
- `vocabulary` — words to weave in / encourage.
- A fixed instruction tail: *"Reply with one short coach turn (≤ 2 sentences). Emit `[[END_LESSON]]` when objectives are covered."*

The assembled prompt is unit-tested so future drift is caught immediately.

### 17.7 LLM Client (`server/llm_client.py`)
Exposes (or extends) `generate(messages: list[dict], max_tokens: int) -> str` so realtime can pass full chat history. The existing `llm.py` factory + retry + Claude→GPT fallback remain authoritative; this is an additional thin wrapper to keep `coach_realtime` decoupled from transport details.

### 17.8 REST Surface (extended, not replaced)
The two existing routes gain mode-aware payloads:

| Route | Body | Response |
|---|---|---|
| `POST /api/lesson/start` | `{lesson_id: str}` | `{session_id, mode, first_agent_utterance}` |
| `POST /api/lesson/turn` | `{session_id, user_text}` | `{agent_utterance, turn_index, done}` |

Scripted sessions return the same fields; `mode` is informational so the UI can label the session.

### 17.9 Curriculum Example (`curriculum/week1/day2.yml`)
Ships in this phase as the first realtime lesson and as the e2e test fixture:
- `mode: realtime`
- `topic: "tools and APIs"`
- ≥ 5 entries in `target_phrases`
- ≥ 8 entries in `vocabulary`
- Non-empty `coach_persona`

### 17.10 Test Strategy
- **Unit (pytest)** — `test_lesson_loader.py` covers default mode, per-required-field validation for realtime, invalid-mode fallback warning, and W1D2 loading. `test_coach_realtime.py` covers `start_session` LLM call, history append, end-on-max-turns, end-on-sentinel, and unknown-session `KeyError`.
- **Regression (pytest)** — `test_coach_scripted_regression.py` snapshots W1D1's full turn sequence to guarantee no behavioral drift in scripted mode.
- **Integration (FastAPI TestClient)** — `test_api_realtime.py` exercises `start` + three `turn` calls against a mocked LLM.
- **E2E (Playwright)** — `tests/e2e/realtime_lesson.spec.ts` boots the app with `LLM_MOCK=1 STT_MOCK=1 TTS_MOCK=1`, selects W1D2, drives 3 mocked user utterances, and asserts the transcript pane renders one initial agent line plus three response lines and that `done` is still false before turn 6. Mock LLM lives at `tests/e2e/mocks/llm_mock.py` and returns a deterministic canned sequence.

### 17.11 Risks & Mitigations
| Risk | Mitigation |
|---|---|
| LLM nondeterminism makes tests flaky. | Inject `LLM_MOCK` in every automated path; never call the real gateway from CI. |
| Long-lived in-memory sessions leak. | 30-minute TTL eviction in `_SESSIONS`. |
| LLM drifts off-topic between turns. | System prompt is built from a constants template that is unit-tested; lesson YAML constrains `topic` / `target_phrases` / `vocabulary`. |
| Adding `mode` silently breaks existing curriculum YAML. | Default to `scripted` on absence; emit WARN on invalid value rather than throwing. |
| Realtime introduces hidden differences in scripted output. | Snapshot regression test on W1D1 turn sequence enforces byte-identical scripted behavior. |

### 17.12 Out of Scope for Phase 2
- Token-by-token streaming responses (Phase 3).
- Per-turn pronunciation scoring changes.
- Curriculum entries beyond `w1d2`.
