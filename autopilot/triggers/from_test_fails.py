"""Parse a pytest log; file one backlog item per failure."""
import re
from typing import List, Dict
from autopilot.backlog import Item


_LINE_RE = re.compile(r"^(tests/[\w/.\-]+\.py)::([\w\[\]\-]+) FAILED", re.MULTILINE)


def parse_pytest_failures(log_text: str) -> List[Dict]:
    out = []
    for m in _LINE_RE.finditer(log_text):
        out.append({"nodeid": f"{m.group(1)}::{m.group(2)}", "test": m.group(2), "file": m.group(1)})
    return out


def _slug(failure: Dict) -> str:
    return "fix-" + failure["test"][:50]


def discover(pytest_log: str = "pytest.log") -> List[Item]:
    try:
        with open(pytest_log, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return []
    failures = parse_pytest_failures(text)
    items: List[Item] = []
    for f in failures:
        items.append(Item(
            slug=_slug(f),
            priority=8,
            source="test_fails",
            prompt=(
                f"The pytest test `{f['nodeid']}` is failing. "
                f"Read the test in {f['file']}, find the bug in the code under test, fix it, "
                f"and verify the test passes. Do not modify the test itself unless the test is wrong."
            ),
        ))
    return items
