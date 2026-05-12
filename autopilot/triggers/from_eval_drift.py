"""Compare current eval pass rate vs baseline; >5pp drop -> high-priority item."""
import json
import os
from typing import List
from autopilot.backlog import Item


def discover(baseline: str = "tests/eval/baseline.json",
             current: str = "tests/eval/current.json") -> List[Item]:
    if not (os.path.exists(baseline) and os.path.exists(current)):
        return []
    with open(baseline, encoding="utf-8") as f:
        b = json.load(f)
    with open(current, encoding="utf-8") as f:
        c = json.load(f)
    drop = float(b.get("pass_rate", 0)) - float(c.get("pass_rate", 0))
    if drop <= 0.05:
        return []
    return [Item(
        slug="eval-drift-investigation",
        priority=9,
        source="eval_drift",
        prompt=(
            f"Eval pass-rate dropped by {drop:.1%} (baseline {b.get('pass_rate')}, "
            f"current {c.get('pass_rate')}). Bisect recent commits, identify the regression, "
            f"propose a fix, and ensure the eval suite returns to baseline."
        ),
    )]
