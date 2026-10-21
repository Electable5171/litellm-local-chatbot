import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.db import repo
from app.main import create_app
from app.services.conversations import clean_title
from tests.test_chat_api import URL, USAGE, chunk, sse_response


def title_reply(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "t",
            "object": "chat.completion",
            "created": 0,
            "model": "qwen3.8",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": text},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def make_router(title: httpx.Response | None = None):
    """Streaming requests get an answer; the non-streaming one is the title request."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if body.get("stream"):
            return sse_response(
                chunk({"content": "Paris is the capital of France."}),
                chunk(finish="stop"),
                chunk(usage=USAGE, empty_choices=True),
            )
        return title or title_reply("Capital of France")

    respx.post(URL).mock(side_effect=handler)
    return seen


def titled(settings):
    return settings.model_copy(update={"auto_titles": True})


def ask(client, conv_id, text="What is the capital of France?"):
    return client.post(f"/api/conversations/{conv_id}/messages", json={"content": text})


def settle(client):
    client.portal.call(client.app.state.conversations.wait_idle)


def get(client, conv_id):
    return client.get(f"/api/conversations/{conv_id}").json()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Capital of France", "Capital of France"),
        ('"Capital of France."', "Capital of France"),
        ("Title: Capital of France", "Capital of France"),
        ("**Capital of France**\nA longer explanation follows.", "Capital of France"),
        ("“Capital of France”", "Capital of France"),
        ("   ", None),
        ("", None),
        ("x" * 90, None),
    ],
)
def test_clean_title(raw, expected):
    assert clean_title(raw) == expected


@respx.mock
def test_the_model_writes_a_title_after_the_first_answer(settings):
    seen = make_router()
    with TestClient(create_app(titled(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        ask(client, conv["id"])
        settle(client)
        assert get(client, conv["id"])["title"] == "Capital of France"
    request = [b for b in seen if not b.get("stream")][0]
    assert request["chat_template_kwargs"] == {"enable_thinking": False}
    assert request["max_tokens"] == 40
    assert request["messages"][0]["role"] == "system"
    text = request["messages"][1]["content"]
    assert "What is the capital of France?" in text and "Paris is the capital" in text


@respx.mock
def test_the_draft_title_is_there_until_the_model_answers(settings):
    make_router()
    with TestClient(create_app(settings)) as client:  # titles off: the draft stays
        conv = client.post("/api/conversations", json={}).json()
        ask(client, conv["id"])
        assert get(client, conv["id"])["title"] == "What is the capital of France?"


@respx.mock
def test_only_one_title_request_per_chat(settings):
    seen = make_router()
    with TestClient(create_app(titled(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        ask(client, conv["id"])
        settle(client)
        ask(client, conv["id"], "And Germany?")
        settle(client)
    assert len([b for b in seen if not b.get("stream")]) == 1


@respx.mock
def test_a_rename_while_the_model_is_writing_the_title_wins(settings):
    app = create_app(titled(settings))
    holder: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("stream"):
            return sse_response(
                chunk({"content": "Paris."}),
                chunk(finish="stop"),
                chunk(usage=USAGE, empty_choices=True),
            )
        # the user renames the chat while this request is in flight
        app.state.db.run_sync(
            lambda c: repo.update_conversation(c, holder["id"], title="My own name")
        )
        return title_reply("Generated title")

    respx.post(URL).mock(side_effect=handler)
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        holder["id"] = conv["id"]
        ask(client, conv["id"])
        settle(client)
        assert get(client, conv["id"])["title"] == "My own name"


@respx.mock
def test_chats_from_before_this_feature_keep_their_titles(settings):
    seen = make_router()
    app = create_app(titled(settings))
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        app.state.db.run_sync(
            lambda c: repo.update_conversation(c, conv["id"], title="Old title")
        )  # title_source 'user'
        ask(client, conv["id"])
        settle(client)
        assert get(client, conv["id"])["title"] == "Old title"
    assert [b for b in seen if not b.get("stream")] == []


@respx.mock
def test_failure_keeps_the_draft_and_does_not_disturb_the_chat(settings):
    make_router(title=httpx.Response(429, json={"error": {"message": "cooldown"}}))
    with TestClient(create_app(titled(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        ask(client, conv["id"])
        settle(client)
        data = get(client, conv["id"])
    assert data["title"] == "What is the capital of France?"
    assert data["messages"][-1]["status"] == "complete"


@respx.mock
def test_an_unusable_reply_keeps_the_draft(settings):
    make_router(title=title_reply("   "))
    with TestClient(create_app(titled(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        ask(client, conv["id"])
        settle(client)
        assert get(client, conv["id"])["title"] == "What is the capital of France?"


@respx.mock
def test_no_title_request_while_another_answer_is_being_written(settings):
    seen = make_router()
    app = create_app(titled(settings))
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        ask(client, conv["id"])
        settle(client)
        # put the title back to a draft, then pretend another chat is streaming
        app.state.db.run_sync(
            lambda c: c.execute("UPDATE conversations SET title_source = 'draft'")
        )
        before = len(seen)
        app.state.conversations._active.add("other-answer")
        client.portal.call(app.state.conversations._write_title, conv["id"])
        assert len(seen) == before
        app.state.conversations._active.discard("other-answer")
        client.portal.call(app.state.conversations._write_title, conv["id"])
        assert len(seen) == before + 1


@respx.mock
def test_a_stopped_or_failed_first_answer_gets_no_title_request(settings):
    seen = make_router()
    app = create_app(titled(settings))
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        ask(client, conv["id"])
        settle(client)
        # a chat whose only answer failed
        other = client.post("/api/conversations", json={}).json()
        ask(client, other["id"], "second chat")
        settle(client)
        msgs = app.state.db.run_sync(lambda c: repo.list_messages(c, other["id"]))
        app.state.db.run_sync(lambda c: repo.update_message(c, msgs[-1]["id"], status="error"))
        app.state.db.run_sync(
            lambda c: c.execute(
                "UPDATE conversations SET title_source = 'draft' WHERE id = ?", (other["id"],)
            )
        )
        before = len([b for b in seen if not b.get("stream")])
        client.portal.call(app.state.conversations._write_title, other["id"])
    assert len([b for b in seen if not b.get("stream")]) == before
