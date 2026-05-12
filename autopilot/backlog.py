"""JSONL-backed prioritized backlog with dedup-by-slug and needs-human filter."""
import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Item:
    slug: str
    priority: int
    source: str
    prompt: str
    tags: List[str] = field(default_factory=list)
    status: str = "open"  # open | done


class Backlog:
    def __init__(self, path: str = "autopilot/backlog.jsonl"):
        self.path = path
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

    def _read(self) -> List[Item]:
        if not os.path.exists(self.path):
            return []
        latest: dict[str, Item] = {}
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                latest[d["slug"]] = Item(**d)
        return list(latest.values())

    def _write_append(self, item: Item) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

    def add(self, item: Item) -> None:
        self._write_append(item)

    def all_open(self) -> List[Item]:
        return [i for i in self._read() if i.status == "open"]

    def pick(self) -> Optional[Item]:
        candidates = [i for i in self.all_open() if "needs-human" not in i.tags]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x.priority, reverse=True)
        return candidates[0]

    def mark_done(self, slug: str) -> None:
        items = self._read()
        for i in items:
            if i.slug == slug:
                i.status = "done"
                self._write_append(i)
                return
