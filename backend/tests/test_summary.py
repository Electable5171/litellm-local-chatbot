import json

import httpx
import respx
from fastapi.testclient import TestClient

from app.db import repo
from app.main import create_app
from app.services.conversations import SUMMARY_NOTE
from tests.test_chat_api import URL, USAGE, chunk, sse_response
from tests.test_titles import title_reply

LONG = "word " * 150  # about 250 tokens


def small(settings, **extra):
    # budget = 1400 - 300 reserved - 256 margin = 844 tokens for the request
    return settings.model_copy(
        update={
            "context_budget_tokens": 1400,
            "max_output_tokens": 300,
            "auto_summary": True,
            **extra,
        }
    )


def router(summary: httpx.Response | None = None):
    """Streaming requests get a short answer; non-streaming ones are summary requests."""
    streamed: list[dict] = []
    summarized: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("stream"):
            streamed.append(body)
            return sse_response(
                chunk({"content": "ok " + LONG}),
                chunk(finish="stop"),
                chunk(usage=USAGE, empty_choices=True),
            )
        summarized.append(body)
        return summary or title_reply("They discussed numbered questions.")

    respx.post(URL).mock(side_effect=handler)
    return streamed, summarized


def say(client, conv_id, text):
    r = client.post(f"/api/conversations/{conv_id}/messages", json={"content": text})
    assert r.status_code == 200
    client.portal.call(client.app.state.conversations.wait_idle)


def context(client, conv_id):
    return client.get(f"/api/conversations/{conv_id}/context").json()


@respx.mock
def test_a_long_chat_is_summarized_and_nothing_is_deleted(settings):
    streamed, summarized = router()
    with TestClient(create_app(small(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        for i in range(3):
            say(client, conv["id"], f"question number {i}")
        shown = client.get(f"/api/conversations/{conv['id']}").json()["messages"]
        data = context(client, conv["id"])
    assert len(summarized) >= 1
    request = summarized[0]
    assert request["chat_template_kwargs"] == {"enable_thinking": False}
    assert request["max_tokens"] == 1000
    assert "question number 0" in request["messages"][1]["content"]
    assert len(shown) == 6  # every message is still there
    assert data["summary"] == "They discussed numbered questions."
    assert data["summarized"] > 0 and data["parts"]["summary"] > 0
    assert data["messages"] + data["summarized"] == 6
    assert data["would_trim"] == 0


@respx.mock
def test_the_next_request_carries_the_summary_instead_of_the_old_messages(settings):
    streamed, _ = router()
    with TestClient(create_app(small(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        for i in range(3):
            say(client, conv["id"], f"question number {i}")
        say(client, conv["id"], "the newest question")
    sent = streamed[-1]["messages"]
    assert sent[0]["role"] == "system"
    assert sent[0]["content"] == SUMMARY_NOTE + "They discussed numbered questions."
    texts = " ".join(m["content"] for m in sent)
    assert "question number 0" not in texts  # covered by the summary
    assert sent[-1]["content"] == "the newest question"
    assert sent[1]["role"] == "user"  # the kept part starts with a question


@respx.mock
def test_a_short_chat_is_left_alone(settings):
    _, summarized = router()
    with TestClient(create_app(small(settings, context_budget_tokens=32_768))) as client:
        conv = client.post("/api/conversations", json={}).json()
        say(client, conv["id"], "hello")
        data = context(client, conv["id"])
    assert summarized == [] and data["summary"] is None and data["summarized"] == 0


@respx.mock
def test_it_can_be_switched_off(settings):
    _, summarized = router()
    with TestClient(create_app(small(settings, auto_summary=False))) as client:
        conv = client.post("/api/conversations", json={}).json()
        for i in range(3):
            say(client, conv["id"], f"question number {i}")
    assert summarized == []


@respx.mock
def test_editing_a_summarized_message_drops_the_summary(settings):
    streamed, _ = router()
    app = create_app(small(settings))
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        base = f"/api/conversations/{conv['id']}"
        for i in range(3):
            say(client, conv["id"], f"question number {i}")
        assert context(client, conv["id"])["summary"]
        first = client.get(base).json()["messages"][0]
        client.post(f"{base}/messages/{first['id']}/edit", json={"content": "a new start"})
        sent = streamed[-1]["messages"]
        assert all(SUMMARY_NOTE not in m["content"] for m in sent)  # not used for this request
        stored = app.state.db.run_sync(lambda c: repo.get_conversation(c, conv["id"]))
    assert stored["summary"] == "" and stored["summary_through"] == 0


@respx.mock
def test_regenerating_the_last_answer_keeps_the_summary(settings):
    streamed, _ = router()
    with TestClient(create_app(small(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        base = f"/api/conversations/{conv['id']}"
        for i in range(3):
            say(client, conv["id"], f"question number {i}")
        client.post(f"{base}/regenerate")
        sent = streamed[-1]["messages"]
        data = context(client, conv["id"])
    assert sent[0]["content"].startswith(SUMMARY_NOTE)
    assert data["summary"]


@respx.mock
def test_a_failed_summary_changes_nothing_and_is_not_retried_at_once(settings):
    streamed, summarized = router(httpx.Response(429, json={"error": {"message": "busy"}}))
    with TestClient(create_app(small(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        for i in range(4):
            say(client, conv["id"], f"question number {i}")
        data = context(client, conv["id"])
    assert len(summarized) == 1  # one try, then a pause
    assert data["summary"] is None and data["summarized"] == 0
    assert len(streamed) == 4  # the chat itself was not affected


@respx.mock
def test_an_empty_reply_is_not_stored_as_a_summary(settings):
    _, summarized = router(title_reply("  "))
    with TestClient(create_app(small(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        for i in range(3):
            say(client, conv["id"], f"question number {i}")
        data = context(client, conv["id"])
    assert summarized and data["summary"] is None


@respx.mock
def test_a_second_summary_builds_on_the_first(settings):
    _, summarized = router()
    with TestClient(create_app(small(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        for i in range(8):
            say(client, conv["id"], f"question number {i}")
        data = context(client, conv["id"])
    assert len(summarized) >= 2
    assert "Earlier summary:" in summarized[1]["messages"][1]["content"]
    assert data["percent"] <= 100 and data["would_trim"] == 0
