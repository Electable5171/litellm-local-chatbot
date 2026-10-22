import json

import httpx
import respx
from fastapi.testclient import TestClient

from app.db import repo
from app.main import create_app
from tests.test_chat_api import URL, USAGE, chunk, parse_sse, sse_response


def reply(text: str):
    return sse_response(
        chunk({"content": text}), chunk(finish="stop"), chunk(usage=USAGE, empty_choices=True)
    )


def conversation_with_two_turns(client):
    conv = client.post("/api/conversations", json={}).json()
    base = f"/api/conversations/{conv['id']}"
    client.post(f"{base}/messages", json={"content": "first question"})
    client.post(f"{base}/messages", json={"content": "second question"})
    return conv["id"], base


@respx.mock
def test_editing_replaces_that_message_and_everything_after_it(settings):
    route = respx.post(URL).mock(side_effect=[reply("a1"), reply("a2"), reply("new answer")])
    with TestClient(create_app(settings)) as client:
        _, base = conversation_with_two_turns(client)
        before = client.get(base).json()["messages"]
        assert [m["content"] for m in before] == ["first question", "a1", "second question", "a2"]

        r = client.post(
            f"{base}/messages/{before[2]['id']}/edit", json={"content": "better second question"}
        )
        assert r.status_code == 200
        names = [n for n, _ in parse_sse(r.text)]
        assert names[0] == "meta" and "done" in names
        after = client.get(base).json()["messages"]
        assert [(m["role"], m["content"]) for m in after] == [
            ("user", "first question"),
            ("assistant", "a1"),
            ("user", "better second question"),
            ("assistant", "new answer"),
        ]
        # the old messages are gone, not hidden
        old_ids = {before[2]["id"], before[3]["id"]}
        assert old_ids.isdisjoint({m["id"] for m in after})
    sent = json.loads(route.calls[2].request.content)["messages"]
    assert [m["content"] for m in sent] == ["first question", "a1", "better second question"]


@respx.mock
def test_editing_the_first_message_restarts_the_whole_conversation(settings):
    route = respx.post(URL).mock(side_effect=[reply("a1"), reply("a2"), reply("fresh")])
    app = create_app(settings)
    with TestClient(app) as client:
        conv_id, base = conversation_with_two_turns(client)
        first = client.get(base).json()["messages"][0]
        client.post(f"{base}/messages/{first['id']}/edit", json={"content": "a different start"})
        after = client.get(base).json()
        assert [m["content"] for m in after["messages"]] == ["a different start", "fresh"]
        positions = app.state.db.run_sync(
            lambda c: [m["position"] for m in repo.list_messages(c, conv_id)]
        )
        assert positions == [1, 2]
        # the draft title follows the new first question
        assert after["title"] == "a different start"
    assert [m["content"] for m in json.loads(route.calls[2].request.content)["messages"]] == [
        "a different start"
    ]


@respx.mock
def test_a_title_written_by_the_model_or_the_user_is_kept_when_the_first_message_is_edited(
    settings,
):
    respx.post(URL).mock(side_effect=[reply("a1"), reply("fresh")])
    app = create_app(settings)
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        base = f"/api/conversations/{conv['id']}"
        client.post(f"{base}/messages", json={"content": "first question"})
        client.patch(base, json={"title": "My own name"})
        first = client.get(base).json()["messages"][0]
        client.post(f"{base}/messages/{first['id']}/edit", json={"content": "other start"})
        assert client.get(base).json()["title"] == "My own name"


@respx.mock
def test_a_failed_edit_leaves_the_conversation_untouched(settings):
    respx.post(URL).mock(
        side_effect=[
            reply("a1"),
            httpx.Response(401, json={"error": {"message": "bad key"}}),
        ]
    )
    with TestClient(create_app(settings)) as client:
        conv = client.post("/api/conversations", json={}).json()
        base = f"/api/conversations/{conv['id']}"
        client.post(f"{base}/messages", json={"content": "q"})
        before = client.get(base).json()["messages"]
        r = client.post(f"{base}/messages/{before[0]['id']}/edit", json={"content": "edited"})
        assert r.status_code >= 400
        assert client.get(base).json()["messages"] == before  # nothing was deleted


@respx.mock
def test_edit_refuses_bad_targets(settings):
    respx.post(URL).mock(return_value=reply("a1"))
    with TestClient(create_app(settings)) as client:
        conv = client.post("/api/conversations", json={}).json()
        other = client.post("/api/conversations", json={}).json()
        base = f"/api/conversations/{conv['id']}"
        client.post(f"{base}/messages", json={"content": "q"})
        user_msg, assistant_msg = client.get(base).json()["messages"]

        def code(r):
            return r.status_code, r.json()["error"]["code"]

        edit = lambda cid, mid, text="x": client.post(  # noqa: E731
            f"/api/conversations/{cid}/messages/{mid}/edit", json={"content": text}
        )
        assert code(edit(conv["id"], assistant_msg["id"])) == (400, "invalid_messages")
        assert code(edit(conv["id"], "nope")) == (404, "message_not_found")
        assert code(edit(other["id"], user_msg["id"])) == (404, "message_not_found")  # not theirs
        assert code(edit("nope", user_msg["id"])) == (404, "conversation_not_found")
        assert code(edit(conv["id"], user_msg["id"], "   ")) == (400, "invalid_messages")
        assert len(client.get(base).json()["messages"]) == 2


@respx.mock
def test_edit_is_refused_while_an_answer_is_being_written(settings):
    respx.post(URL).mock(return_value=reply("a1"))
    app = create_app(settings)
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        base = f"/api/conversations/{conv['id']}"
        client.post(f"{base}/messages", json={"content": "q"})
        user_msg, assistant_msg = client.get(base).json()["messages"]
        app.state.db.run_sync(
            lambda c: repo.update_message(c, assistant_msg["id"], status="streaming")
        )
        app.state.conversations._active.add(assistant_msg["id"])
        r = client.post(f"{base}/messages/{user_msg['id']}/edit", json={"content": "x"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "conversation_busy"


@respx.mock
def test_editing_after_a_stopped_or_failed_answer_works(settings):
    respx.post(URL).mock(side_effect=[reply("a1"), reply("again")])
    app = create_app(settings)
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        base = f"/api/conversations/{conv['id']}"
        client.post(f"{base}/messages", json={"content": "q"})
        user_msg, assistant_msg = client.get(base).json()["messages"]
        app.state.db.run_sync(lambda c: repo.update_message(c, assistant_msg["id"], status="error"))
        client.post(f"{base}/messages/{user_msg['id']}/edit", json={"content": "q again"})
        assert [m["content"] for m in client.get(base).json()["messages"]] == ["q again", "again"]
