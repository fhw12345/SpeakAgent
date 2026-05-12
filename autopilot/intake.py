"""Intake: turn a one-line user request into a PRD draft + backlog items.

Usage:
    python -m autopilot.intake "做阶段 1 session 列表 UI"

Flow:
1. Generate a unique slug + timestamp
2. Call LLM (Claude) to expand the request into a PRD-style markdown document
3. Save to autopilot/prds/<date>-<slug>.md
4. Call LLM again to break the PRD into 3-8 bite-sized backlog items
5. Add each item to autopilot/backlog.jsonl

The PRD is the source of truth the implementer subagent works from.
Each backlog item references its parent PRD path so the implementer can read it.

NOTE: This module talks to the Claude gateway directly (urllib) instead of
going through server.llm.call_with_fallback because the PRD generator needs
a much larger max_tokens than the conversational scoring path. Keeping the
two callers separate also matches spec §9.2's "do not modify server/llm.py"
escalation rule for autopilot work.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import uuid
from typing import List

from autopilot.backlog import Backlog, Item
from server.logging_setup import configure_logging, get_logger

configure_logging()
_log = get_logger("intake")


_GATEWAY = os.environ.get(
    "CLAUDE_API_ENDPOINT",
    "http://localhost:23333/api/anthropic/v1/messages",
)
_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4.7-1m-internal")


def _llm_call(prompt: str, system: str, max_tokens: int = 4096) -> str:
    """Direct Claude gateway call with configurable max_tokens; 3-retry."""
    body = json.dumps({
        "model": _MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                _GATEWAY, data=body,
                headers={"Content-Type": "application/json",
                         "anthropic-version": "2023-06-01"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block["text"].strip()
            return ""
        except Exception as e:
            last_err = e
            wait = (attempt + 1) * 10
            _log.warning("llm_retry", attempt=attempt + 1, error=str(e)[:200], wait_s=wait)
            if attempt < 2:
                time.sleep(wait)
    raise RuntimeError(f"llm_call failed after 3 attempts: {last_err}")


_PRD_SYSTEM = (
    "You are a product manager writing a PRD for a single agentic coding agent to implement. "
    "The agent will read your PRD and produce code+tests with no further human input. "
    "Your PRD must be SPECIFIC: name files, name functions, name types, list endpoints, list tests. "
    "Do NOT write fluff. Do NOT write 'TBD'. Do NOT write 'consider'. "
    "Output sections in this exact order, all in markdown:\n"
    "## Goal (1-2 sentences)\n"
    "## Acceptance Criteria (numbered list, each testable)\n"
    "## Files to Create or Modify (bullet list with one-line purpose each)\n"
    "## Public Interface (function signatures, REST routes, WS message types)\n"
    "## Test Plan (unit tests + integration tests + Playwright e2e if frontend involved)\n"
    "## Out of Scope (1-3 bullets)\n"
    "## Risks (1-3 bullets with mitigations)"
)


_BACKLOG_SYSTEM = (
    "You are a tech lead breaking a PRD into 3-8 backlog items for parallel agent execution. "
    "Each item must be: independently committable, completable in <30 minutes, name exact files. "
    "Reply ONLY with JSON: a list of objects, each with keys "
    '{"slug": str, "priority": int 1-10, "prompt": str}. '
    "The prompt is what the implementer agent will read; it must reference the PRD path "
    "and tell the agent exactly what to do. Order items by dependency (item 1 first)."
)


def _slugify(text: str, max_len: int = 40) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9一-鿿]+", "-", text)
    text = text.strip("-")
    return text[:max_len] or uuid.uuid4().hex[:8]


def generate_prd(request: str, prd_path: str) -> str:
    """Call LLM to expand request into a PRD; write to prd_path; return markdown."""
    prompt = (
        f"User request: {request!r}\n\n"
        f"Repository context: speakAgent — a local English speaking trainer "
        f"(FastAPI backend on :8765 + vanilla web frontend + faster-whisper STT + "
        f"Azure Speech TTS + Claude LLM via local gateway). "
        f"See docs/superpowers/specs/2026-05-12-speakagent-design.md for full design. "
        f"Code lives in server/, web/, curriculum/, autopilot/, tests/.\n\n"
        f"Write the PRD now."
    )
    md = _llm_call(prompt, system=_PRD_SYSTEM, max_tokens=4096)
    if not md or len(md) < 200:
        raise RuntimeError(f"LLM returned suspiciously short PRD ({len(md)} chars): {md[:100]!r}")
    os.makedirs(os.path.dirname(prd_path), exist_ok=True)
    with open(prd_path, "w", encoding="utf-8") as f:
        f.write(f"# PRD: {request}\n\n")
        f.write(f"_Generated: {datetime.datetime.now().isoformat(timespec='seconds')}_\n\n")
        f.write(md)
        f.write("\n")
    _log.info("prd_written", path=prd_path, chars=len(md))
    return md


def generate_backlog_items(prd_text: str, prd_path: str) -> List[Item]:
    """Call LLM to break PRD into Items; return list (NOT yet added to backlog)."""
    prompt = (
        f"Here is the PRD (path: {prd_path}):\n\n```\n{prd_text}\n```\n\n"
        f"Break it into backlog items now. Reply ONLY with the JSON list."
    )
    raw = _llm_call(prompt, system=_BACKLOG_SYSTEM, max_tokens=2048)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _log.error("backlog_parse_failed", error=str(e), raw=raw[:300])
        raise ValueError(f"LLM did not return valid JSON: {e}\n{raw[:500]}")

    items: List[Item] = []
    for d in data:
        slug = d.get("slug") or _slugify(d.get("prompt", "")[:40])
        items.append(Item(
            slug=slug,
            priority=int(d.get("priority", 5)),
            source="intake",
            prompt=(
                f"PRD: {prd_path}\n\n"
                f"Read the PRD first, then implement this slice:\n\n"
                f"{d['prompt']}\n\n"
                f"Constraints: TDD (test first), commit on completion, "
                f"do not modify autopilot/ or server/llm.py."
            ),
            tags=["intake"],
        ))
    return items


def intake(request: str, dry_run: bool = False) -> dict:
    """Main entry. Returns {prd_path, items_added, item_slugs}."""
    today = datetime.date.today().isoformat()
    slug = _slugify(request, max_len=30)
    prd_path = f"autopilot/prds/{today}-{slug}.md"

    _log.info("intake_start", request=request, prd_path=prd_path)

    prd_text = generate_prd(request, prd_path)
    items = generate_backlog_items(prd_text, prd_path)

    if dry_run:
        _log.info("intake_dry_run", item_count=len(items))
        return {"prd_path": prd_path, "items_added": 0, "item_slugs": [i.slug for i in items], "dry_run": True}

    bl = Backlog()
    for item in items:
        bl.add(item)
    _log.info("intake_done", item_count=len(items), slugs=[i.slug for i in items])

    return {
        "prd_path": prd_path,
        "items_added": len(items),
        "item_slugs": [i.slug for i in items],
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m autopilot.intake \"<one-line request>\" [--dry-run]")
        sys.exit(1)
    dry_run = "--dry-run" in sys.argv
    request = " ".join(a for a in sys.argv[1:] if a != "--dry-run")
    result = intake(request, dry_run=dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
