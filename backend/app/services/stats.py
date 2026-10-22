"""Usage figures worked out from the answers stored on this computer.

Only what this app stored is counted (LiteLLM's own spend log is the source for everything the
whole team uses). Days follow the browser's time zone, which it passes as minutes east of UTC.
"""

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db import repo
from app.db.database import Database

RANGES = ("today", "7d", "30d", "all")
MAX_DAYS = 90  # the per-day chart for "all" shows the most recent 90 days
SLOWEST = 5


def percentile(sorted_values: list[int], p: float) -> int | None:
    """Nearest-rank percentile (0-100) of an ascending list."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(p / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def _summary(values: list[int]) -> dict[str, int | None]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "avg": round(sum(ordered) / len(ordered)) if ordered else None,
        "p50": percentile(ordered, 50),
        "p95": percentile(ordered, 95),
        "max": ordered[-1] if ordered else None,
    }


def window_start(range_name: str, now: datetime, tz_minutes: int) -> datetime | None:
    """The UTC moment the range begins, or None for "all"."""
    if range_name == "all":
        return None
    offset = timedelta(minutes=tz_minutes)
    local_midnight = (now + offset).replace(hour=0, minute=0, second=0, microsecond=0)
    days = {"today": 0, "7d": 6, "30d": 29}[range_name]
    return local_midnight - timedelta(days=days) - offset


def compute(
    rows: list[dict[str, Any]], range_name: str, now: datetime, tz_minutes: int
) -> dict[str, Any]:
    offset = timedelta(minutes=tz_minutes)
    done = [r for r in rows if r["status"] == "complete"]
    latency = [r["latency_ms"] for r in done if r["latency_ms"] is not None]
    ttft = [r["ttft_ms"] for r in done if r["ttft_ms"] is not None]
    thinking = [r["thinking_ms"] for r in done if r["thinking_ms"] is not None]
    speeds = [
        r["completion_tokens"] / (r["latency_ms"] / 1000)
        for r in done
        if r["completion_tokens"] and r["latency_ms"]
    ]

    def local_day(row: dict[str, Any]) -> str:
        return (datetime.fromisoformat(row["created_at"]) + offset).date().isoformat()

    by_day: dict[str, dict[str, int]] = {}
    for r in done:
        day = by_day.setdefault(local_day(r), {"answers": 0, "completion_tokens": 0})
        day["answers"] += 1
        day["completion_tokens"] += r["completion_tokens"] or 0

    today = (now + offset).date()
    start = window_start(range_name, now, tz_minutes)
    if start is not None:
        first = (start + offset).date()
    else:
        first = min((datetime.fromisoformat(d).date() for d in by_day), default=today)
        first = max(first, today - timedelta(days=MAX_DAYS - 1))
    per_day = []
    for n in range((today - first).days + 1):
        key = (first + timedelta(days=n)).isoformat()
        per_day.append({"date": key, **by_day.get(key, {"answers": 0, "completion_tokens": 0})})

    slowest = sorted(
        (r for r in done if r["latency_ms"] is not None),
        key=lambda r: r["latency_ms"],
        reverse=True,
    )[:SLOWEST]
    return {
        "range": range_name,
        "since": start.isoformat() if start else None,
        "answers": {
            "complete": len(done),
            "stopped": sum(1 for r in rows if r["status"] == "cancelled"),
            "failed": sum(1 for r in rows if r["status"] == "error"),
        },
        "tokens": {
            "prompt": sum(r["prompt_tokens"] or 0 for r in done),
            "completion": sum(r["completion_tokens"] or 0 for r in done),
        },
        "latency_ms": _summary(latency),
        "ttft_ms": _summary(ttft),
        "thinking_ms": _summary(thinking),
        "tokens_per_second": round(sum(speeds) / len(speeds), 1) if speeds else None,
        "conversations": len({r["conversation_id"] for r in rows}),
        "per_day": per_day,
        "slowest": [
            {
                "message_id": r["id"],
                "conversation_id": r["conversation_id"],
                "title": r["title"] or "New chat",
                "latency_ms": r["latency_ms"],
                "completion_tokens": r["completion_tokens"],
                "created_at": r["created_at"],
            }
            for r in slowest
        ],
    }


class StatsService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def stats(self, range_name: str, tz_minutes: int = 0) -> dict[str, Any]:
        now = datetime.now(UTC)
        start = window_start(range_name, now, tz_minutes)

        def load(conn):
            return repo.answers_since(
                conn, start.isoformat(timespec="milliseconds") if start else None
            )

        rows = await self._db.run(load)
        return compute(rows, range_name, now, tz_minutes)
