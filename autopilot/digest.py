"""Markdown daily digest of LoopResults under autopilot/runs/digest-<date>.md."""
import datetime
import os
from typing import List

from autopilot.loop import LoopResult


def write_digest(results: List[LoopResult], runs_dir: str = "autopilot/runs",
                 date_str: str = None) -> str:
    os.makedirs(runs_dir, exist_ok=True)
    date_str = date_str or datetime.date.today().isoformat()
    path = os.path.join(runs_dir, f"digest-{date_str}.md")
    counts = {"committed": 0, "needs_human": 0, "idle": 0, "paused": 0, "error": 0}
    lines: List[str] = [f"# Autopilot digest — {date_str}", ""]
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status == "committed":
            lines.append(f"- **committed** `{r.item_slug}` → branch `{r.branch}`")
        elif r.status == "needs_human":
            lines.append(f"- **needs_human** `{r.item_slug}` — {r.detail}")
        elif r.status == "paused":
            lines.append("- _paused (PAUSE file present)_")
        elif r.status == "idle":
            lines.append("- _idle (no backlog items)_")
        else:
            lines.append(f"- **{r.status}** {r.detail}")
    lines += ["", "## Summary", ""]
    for k, v in counts.items():
        lines.append(f"- {k}: {v}")
    body = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path
