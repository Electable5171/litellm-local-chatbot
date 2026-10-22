from datetime import UTC, datetime, timedelta

import pytest
import respx
from fastapi.testclient import TestClient

from app.db import repo
from app.main import create_app
from app.services.stats import compute, percentile, window_start
from tests.test_chat_api import URL, USAGE, chunk, sse_response

NOW = datetime(2026, 10, 22, 21, 0, tzinfo=UTC)  # 02:30 on 23 October in India (UTC+5:30)


def row(created: datetime, **kw):
    base = {
        "id": f"m{created.timestamp()}",
        "conversation_id": "c1",
        "title": "Chat",
        "status": "complete",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "latency_ms": 5000,
        "ttft_ms": 400,
        "thinking_ms": 2000,
        "created_at": created.isoformat(timespec="milliseconds"),
    }
    return {**base, **kw}


def test_percentile_is_nearest_rank():
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile(values, 100) == 100
    assert percentile([7], 95) == 7
    assert percentile([], 50) is None


def test_windows_follow_the_local_day():
    # 02:30 local on the 23rd: "today" began at 00:00 local = 18:30 UTC on the 22nd
    assert window_start("today", NOW, 330) == datetime(2026, 10, 22, 18, 30, tzinfo=UTC)
    assert window_start("7d", NOW, 330) == datetime(2026, 10, 16, 18, 30, tzinfo=UTC)
    assert window_start("30d", NOW, 0) == datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
    assert window_start("all", NOW, 330) is None


def test_figures_for_a_few_answers():
    rows = [
        row(
            NOW - timedelta(hours=1),
            latency_ms=2000,
            completion_tokens=100,
            ttft_ms=200,
            thinking_ms=None,
        ),
        row(
            NOW - timedelta(hours=2),
            latency_ms=4000,
            completion_tokens=200,
            ttft_ms=600,
            thinking_ms=1000,
        ),
        row(
            NOW - timedelta(hours=3),
            latency_ms=9000,
            completion_tokens=300,
            ttft_ms=1000,
            thinking_ms=3000,
        ),
        row(NOW - timedelta(hours=4), status="cancelled", latency_ms=None, completion_tokens=None),
        row(NOW - timedelta(hours=5), status="error", latency_ms=None, completion_tokens=None),
    ]
    result = compute(rows, "today", NOW, 330)
    assert result["answers"] == {"complete": 3, "stopped": 1, "failed": 1}
    assert result["tokens"] == {"prompt": 300, "completion": 600}
    assert result["latency_ms"] == {"count": 3, "avg": 5000, "p50": 4000, "p95": 9000, "max": 9000}
    assert result["ttft_ms"]["avg"] == 600
    assert result["thinking_ms"]["count"] == 2 and result["thinking_ms"]["avg"] == 2000
    # 100/2 s, 200/4 s, 300/9 s -> mean of 50, 50, 33.3
    assert result["tokens_per_second"] == pytest.approx(44.4, abs=0.1)
    assert [s["latency_ms"] for s in result["slowest"]] == [9000, 4000, 2000]
    assert result["conversations"] == 1


def test_nothing_in_the_range_gives_empty_figures_not_errors():
    result = compute([], "7d", NOW, 0)
    assert result["answers"] == {"complete": 0, "stopped": 0, "failed": 0}
    assert result["latency_ms"]["avg"] is None and result["tokens_per_second"] is None
    assert result["slowest"] == [] and len(result["per_day"]) == 7


def test_per_day_buckets_use_the_local_day_and_fill_gaps():
    rows = [
        row(datetime(2026, 10, 22, 20, 0, tzinfo=UTC)),  # 01:30 on the 23rd locally
        row(datetime(2026, 10, 22, 10, 0, tzinfo=UTC)),  # 15:30 on the 22nd locally
        row(datetime(2026, 10, 20, 10, 0, tzinfo=UTC), completion_tokens=70),  # the 20th
    ]
    days = {d["date"]: d for d in compute(rows, "7d", NOW, 330)["per_day"]}
    assert len(days) == 7 and "2026-10-17" in days and "2026-10-23" in days
    assert days["2026-10-23"]["answers"] == 1
    assert days["2026-10-22"]["answers"] == 1
    assert days["2026-10-21"] == {"date": "2026-10-21", "answers": 0, "completion_tokens": 0}
    assert days["2026-10-20"]["completion_tokens"] == 70


def test_all_time_chart_is_limited_to_the_last_90_days():
    rows = [row(NOW - timedelta(days=400)), row(NOW)]
    per_day = compute(rows, "all", NOW, 0)["per_day"]
    assert len(per_day) == 90 and per_day[-1]["date"] == "2026-10-22"


def answer():
    return sse_response(
        chunk({"reasoning_content": "hmm"}),
        chunk({"content": "ok"}),
        chunk(finish="stop"),
        chunk(usage=USAGE, empty_choices=True),
    )


@respx.mock
def test_api_reports_what_was_stored(settings):
    respx.post(URL).mock(side_effect=[answer(), answer()])
    with TestClient(create_app(settings)) as client:
        a = client.post("/api/conversations", json={}).json()
        b = client.post("/api/conversations", json={}).json()
        client.post(f"/api/conversations/{a['id']}/messages", json={"content": "q1"})
        client.post(f"/api/conversations/{b['id']}/messages", json={"content": "q2"})
        data = client.get("/api/stats", params={"range": "today", "tz": 0}).json()
        assert data["answers"]["complete"] == 2 and data["conversations"] == 2
        assert data["tokens"] == {"prompt": 50, "completion": 84}  # USAGE twice
        assert data["latency_ms"]["count"] == 2 and data["thinking_ms"]["count"] == 2
        assert len(data["slowest"]) == 2 and data["slowest"][0]["title"] in ("q1", "q2")
        assert sum(d["answers"] for d in data["per_day"]) == 2


def test_api_defaults_and_validation(settings):
    with TestClient(create_app(settings)) as client:
        ok = client.get("/api/stats")
        assert ok.status_code == 200 and ok.json()["range"] == "7d"
        bad = client.get("/api/stats", params={"range": "forever"})
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_range"
        assert client.get("/api/stats", params={"tz": 5000}).status_code == 422


@respx.mock
def test_old_answers_fall_out_of_a_short_range(settings):
    respx.post(URL).mock(return_value=answer())
    app = create_app(settings)
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "q"})
        msgs = app.state.db.run_sync(lambda c: repo.list_messages(c, conv["id"]))
        old = (datetime.now(UTC) - timedelta(days=40)).isoformat(timespec="milliseconds")
        app.state.db.run_sync(
            lambda c: c.execute(
                "UPDATE messages SET created_at = ? WHERE id = ?", (old, msgs[-1]["id"])
            )
        )
        assert client.get("/api/stats", params={"range": "30d"}).json()["answers"]["complete"] == 0
        assert client.get("/api/stats", params={"range": "all"}).json()["answers"]["complete"] == 1
