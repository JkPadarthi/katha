"""Writing rituals — an append-only log of output (1.0).

One JSON line per save, stored in the archive (NOT the rebuildable index):
    archive/.katha/stats/writing.jsonl
    {"ts": ..., "series": ..., "book": ..., "chapter": ..., "words": N, "delta": D}

Counts and streaks are derived by scanning the file — cheap, and the file is
the truth (same md-on-disk philosophy as the rest of the archive).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import ARCHIVE_ROOT

_STATS = ARCHIVE_ROOT / ".katha" / "stats" / "writing.jsonl"


def append_write(ts: str, series: str, book: str, chapter: str,
                 words: int, delta: int) -> None:
    """Append a save to the log. Best-effort — never break a save over stats."""
    try:
        _STATS.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": ts, "series": series, "book": book,
               "chapter": chapter, "words": words, "delta": delta}
        with _STATS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _records() -> list[dict]:
    if not _STATS.is_file():
        return []
    out = []
    for line in _STATS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def daily_totals() -> dict[str, int]:
    """{date: words_added}. Only positive deltas count as progress."""
    totals: dict[str, int] = {}
    for r in _records():
        d = str(r.get("ts", ""))[:10]
        if not d:
            continue
        delta = int(r.get("delta", 0) or 0)
        if delta > 0:
            totals[d] = totals.get(d, 0) + delta
    return totals


def today_words(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return daily_totals().get(now.date().isoformat(), 0)


def compute_streak(goal: int, now: datetime | None = None) -> int:
    """Consecutive days (ending today or yesterday) that met the goal."""
    now = now or datetime.now(timezone.utc)
    totals = daily_totals()
    d = now.date()
    # Today not yet at goal → the streak still counts through yesterday.
    if totals.get(d.isoformat(), 0) < goal:
        d -= timedelta(days=1)
    streak = 0
    while totals.get(d.isoformat(), 0) >= goal:
        streak += 1
        d -= timedelta(days=1)
    return streak


def best_streak(goal: int) -> int:
    totals = daily_totals()
    days = []
    for k, v in totals.items():
        if v >= goal:
            try:
                days.append(date.fromisoformat(k))
            except ValueError:
                continue
    days.sort()
    best = cur = 0
    prev: date | None = None
    for d in days:
        cur = cur + 1 if (prev is not None and (d - prev).days == 1) else 1
        best = max(best, cur)
        prev = d
    return best


def history(days: int = 14, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    totals = daily_totals()
    return [
        {"date": (now.date() - timedelta(days=i)).isoformat(),
         "words": totals.get((now.date() - timedelta(days=i)).isoformat(), 0)}
        for i in range(days - 1, -1, -1)
    ]


def summary(goal: int) -> dict:
    return {
        "today": today_words(),
        "goal": goal,
        "streak": compute_streak(goal),
        "best": best_streak(goal),
        "total": sum(daily_totals().values()),
        "history": history(14),
    }
