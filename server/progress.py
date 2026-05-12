"""Session JSON log + SQLite SM-2 SRS for vocab."""
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Dict, List


def sm2_next(prev_interval: int, prev_ease: float, quality: int) -> Dict:
    """SM-2 algorithm. quality: 0-5. Returns new {interval_days, ease}."""
    if quality < 3:
        return {"interval_days": 1, "ease": max(1.3, prev_ease)}
    if prev_interval == 0:
        new_interval = 1
    elif prev_interval == 1:
        new_interval = 6
    else:
        new_interval = round(prev_interval * prev_ease)
    new_ease = prev_ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ease = max(1.3, new_ease)
    return {"interval_days": new_interval, "ease": round(new_ease, 3)}


class ProgressStore:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.sessions_dir = os.path.join(data_dir, "sessions")
        os.makedirs(self.sessions_dir, exist_ok=True)
        self.db_path = os.path.join(data_dir, "vocab_srs.sqlite")
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS vocab_srs (
                    word TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL,
                    next_review_at TEXT NOT NULL,
                    interval_days INTEGER NOT NULL DEFAULT 0,
                    ease REAL NOT NULL DEFAULT 2.5
                )
            """)

    def _session_path(self, session_id: str) -> str:
        return os.path.join(self.sessions_dir, f"{session_id}.jsonl")

    def append_turn(self, session_id: str, lesson_id: str, turn: Dict) -> None:
        record = {
            "ts": datetime.utcnow().isoformat(),
            "lesson_id": lesson_id,
            **turn,
        }
        with open(self._session_path(session_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_session(self, session_id: str) -> List[Dict]:
        p = self._session_path(session_id)
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def add_words(self, words: List[str]) -> None:
        today = date.today().isoformat()
        with sqlite3.connect(self.db_path) as con:
            for w in words:
                con.execute(
                    "INSERT OR IGNORE INTO vocab_srs(word, first_seen_at, next_review_at) VALUES (?, ?, ?)",
                    (w, today, today),
                )

    def due_words(self, today: date = None) -> List[str]:
        today = today or date.today()
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute(
                "SELECT word FROM vocab_srs WHERE next_review_at <= ?",
                (today.isoformat(),),
            )
            return [r[0] for r in cur.fetchall()]

    def review_word(self, word: str, quality: int) -> None:
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute(
                "SELECT interval_days, ease FROM vocab_srs WHERE word = ?", (word,)
            )
            row = cur.fetchone()
            if not row:
                return
            interval, ease = row
            nxt = sm2_next(interval, ease, quality)
            new_due = (date.today() + timedelta(days=nxt["interval_days"])).isoformat()
            con.execute(
                "UPDATE vocab_srs SET interval_days = ?, ease = ?, next_review_at = ? WHERE word = ?",
                (nxt["interval_days"], nxt["ease"], new_due, word),
            )
