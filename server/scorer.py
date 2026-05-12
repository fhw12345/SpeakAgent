"""Three-dim scoring: pronunciation proxy + fluency + content (LLM judge)."""
import json
from dataclasses import dataclass, field
from typing import List, Dict

from server.llm import call_with_fallback
from server.logging_setup import get_logger

_log = get_logger("scorer")

FILLERS = {"um", "uh", "uhm", "like", "erm", "err"}


@dataclass
class TurnScore:
    pronunciation: float
    fluency: Dict
    content_score: int
    issues: List[str] = field(default_factory=list)
    rewrite: str = ""

    def to_dict(self) -> Dict:
        return {
            "pronunciation": self.pronunciation,
            "fluency": self.fluency,
            "content_score": self.content_score,
            "issues": self.issues,
            "rewrite": self.rewrite,
        }


def _wer(ref: str, hyp: str) -> float:
    """Standard word error rate."""
    r = ref.lower().split()
    h = hyp.lower().split()
    if not r:
        return 0.0 if not h else 1.0
    n, m = len(r), len(h)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if r[i - 1] == h[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[n][m] / n


def _fluency(words: List[Dict]) -> Dict:
    if not words:
        return {"wpm": 0.0, "pauses_over_800ms": 0, "fillers": 0, "duration_s": 0.0}
    duration = max(0.001, words[-1]["end"] - words[0]["start"])
    wpm = (len(words) / duration) * 60.0
    pauses = 0
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        if gap > 0.8:
            pauses += 1
    fillers = sum(1 for w in words if w["w"].lower().strip(",.!?") in FILLERS)
    return {
        "wpm": round(wpm, 1),
        "pauses_over_800ms": pauses,
        "fillers": fillers,
        "duration_s": round(duration, 2),
    }


_JUDGE_SYSTEM = (
    "You are an English-speaking interview coach. Given a spoken answer and an ideal version, "
    "rate content 1-5 (5=excellent), produce a more idiomatic rewrite, and list up to 3 issues. "
    "Reply ONLY with JSON: {\"content_score\": int, \"rewrite\": str, \"issues\": [str]}."
)


def score_turn(
    user_text: str,
    user_words: List[Dict],
    user_confidence: float,
    ideal_text: str,
    llm_system: str = _JUDGE_SYSTEM,
) -> TurnScore:
    wer = _wer(ideal_text, user_text)
    pronunciation = max(0.0, min(1.0, 0.5 * user_confidence + 0.5 * (1.0 - wer)))
    fluency = _fluency(user_words)

    prompt = (
        f"User said: {user_text!r}\n"
        f"Ideal version: {ideal_text!r}\n"
        "Score and rewrite per the system instructions."
    )
    raw = call_with_fallback(prompt, system=llm_system)
    try:
        parsed = json.loads(raw)
        content_score = int(parsed.get("content_score", 3))
        rewrite = str(parsed.get("rewrite", ""))
        issues = list(parsed.get("issues", []))[:3]
    except Exception as e:
        _log.warning("scorer_judge_parse_failed", error=str(e), raw=raw[:200])
        content_score, rewrite, issues = 3, "", []

    return TurnScore(
        pronunciation=round(pronunciation, 3),
        fluency=fluency,
        content_score=content_score,
        issues=issues,
        rewrite=rewrite,
    )
