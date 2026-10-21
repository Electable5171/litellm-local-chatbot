import httpx
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_chat_api import URL, USAGE, chunk, parse_sse, sse_response


def answer(*pieces: str):
    return sse_response(
        *[chunk({"content": p}) for p in pieces],
        chunk(finish="stop"),
        chunk(usage=USAGE, empty_choices=True),
    )


def new(client, **body):
    r = client.post("/api/conversations", json=body)
    assert r.status_code == 201
    return r.json()


def test_crud_and_validation(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/conversations").json() == {"conversations": []}
        conv = new(client)
        assert conv["model"] == "qwen3.8" and conv["thinking"] is True and conv["title"] == ""
        got = client.get(f"/api/conversations/{conv['id']}").json()
        assert got["messages"] == []
        renamed = client.patch(f"/api/conversations/{conv['id']}", json={"title": "  My   chat "})
        assert renamed.json()["title"] == "My chat"
        assert (
            client.patch(f"/api/conversations/{conv['id']}", json={"title": ""}).status_code == 422
        )
        bad = client.patch(f"/api/conversations/{conv['id']}", json={"model": "nope"})
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "model_not_allowed"
        assert client.post("/api/conversations", json={"model": "nope"}).status_code == 400
        assert client.delete(f"/api/conversations/{conv['id']}").status_code == 204
        missing = client.get(f"/api/conversations/{conv['id']}")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "conversation_not_found"
        assert client.delete(f"/api/conversations/{conv['id']}").status_code == 404


@respx.mock
def test_send_saves_question_and_answer_and_titles_the_chat(settings):
    respx.post(URL).mock(return_value=answer("Hel", "lo"))
    with TestClient(create_app(settings)) as client:
        conv = new(client)
        r = client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "Say hi"})
        assert r.status_code == 200
        events = parse_sse(r.text)
        assert [n for n, _ in events] == ["meta", "content", "content", "done"]
        meta = events[0][1]
        assert meta["conversation_id"] == conv["id"] and meta["message_id"]
        got = client.get(f"/api/conversations/{conv['id']}").json()
        assert got["title"] == "Say hi"
        user, reply = got["messages"]
        assert (user["role"], user["content"]) == ("user", "Say hi")
        assert reply["id"] == meta["message_id"]
        assert (reply["status"], reply["content"]) == ("complete", "Hello")
        assert reply["usage"] == {"prompt_tokens": 25, "completion_tokens": 42}
        assert reply["finish_reason"] == "stop" and reply["latency_ms"] is not None


@respx.mock
def test_reasoning_is_saved_with_thinking_time(settings):
    respx.post(URL).mock(
        return_value=sse_response(
            chunk({"reasoning_content": "hmm"}),
            chunk({"content": "391"}),
            chunk(finish="stop"),
        )
    )
    with TestClient(create_app(settings)) as client:
        conv = new(client)
        client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "q"})
        reply = client.get(f"/api/conversations/{conv['id']}").json()["messages"][1]
        assert reply["reasoning"] == "hmm" and reply["thinking_ms"] is not None


@respx.mock
def test_history_and_system_prompt_are_sent_and_thinking_off_is_honoured(settings):
    route = respx.post(URL).mock(side_effect=[answer("one"), answer("two")])
    with TestClient(create_app(settings)) as client:
        conv = new(client, thinking=False, system_prompt="Be brief.")
        base = f"/api/conversations/{conv['id']}"
        client.post(f"{base}/messages", json={"content": "first"})
        client.post(f"{base}/messages", json={"content": "second"})
    import json

    body = json.loads(route.calls[1].request.content)
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("system", "Be brief."),
        ("user", "first"),
        ("assistant", "one"),
        ("user", "second"),
    ]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


@respx.mock
def test_upstream_failure_before_streaming_saves_nothing(settings):
    respx.post(URL).mock(return_value=httpx.Response(401, json={"error": {"message": "bad key"}}))
    with TestClient(create_app(settings)) as client:
        conv = new(client)
        r = client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "hi"})
        assert r.status_code >= 400
        got = client.get(f"/api/conversations/{conv['id']}").json()
        assert got["messages"] == [] and got["title"] == ""


@respx.mock
def test_midstream_error_is_saved_as_error_with_partial_text(settings):
    def broken(request):
        class Boom(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"id":"c","object":"chat.completion.chunk","created":0,"model":"m",'
                yield b'"choices":[{"index":0,"delta":{"content":"par"},"finish_reason":null}]}\n\n'
                raise httpx.ReadError("cut")

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Boom())

    respx.post(URL).mock(side_effect=broken)
    with TestClient(create_app(settings)) as client:
        conv = new(client)
        r = client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "hi"})
        assert parse_sse(r.text)[-1][0] == "error"
        reply = client.get(f"/api/conversations/{conv['id']}").json()["messages"][1]
        assert reply["status"] == "error" and reply["content"] == "par"
        assert reply["error"]["code"] == "upstream_interrupted"


@respx.mock
def test_regenerate_replaces_the_last_answer(settings):
    route = respx.post(URL).mock(side_effect=[answer("old"), answer("new")])
    with TestClient(create_app(settings)) as client:
        conv = new(client)
        base = f"/api/conversations/{conv['id']}"
        client.post(f"{base}/messages", json={"content": "q"})
        r = client.post(f"{base}/regenerate")
        assert r.status_code == 200
        msgs = client.get(base).json()["messages"]
        assert [(m["role"], m["content"]) for m in msgs] == [("user", "q"), ("assistant", "new")]
        assert msgs[0]["id"] == parse_sse(r.text)[0][1]["user_message_id"]
        import json

        sent = json.loads(route.calls[1].request.content)["messages"]
        assert [m["content"] for m in sent] == ["q"]
        # nothing to regenerate in an empty chat
        empty = new(client)
        assert client.post(f"/api/conversations/{empty['id']}/regenerate").status_code == 409


@respx.mock
def test_busy_conversation_is_refused_but_stale_streaming_is_recovered(settings):
    respx.post(URL).mock(return_value=answer("ok"))
    app = create_app(settings)
    with TestClient(app) as client:
        conv = new(client)
        base = f"/api/conversations/{conv['id']}"
        client.post(f"{base}/messages", json={"content": "q"})
        from app.db import repo

        db = app.state.db
        reply = db.run_sync(lambda c: repo.list_messages(c, conv["id"]))[-1]
        db.run_sync(lambda c: repo.update_message(c, reply["id"], status="streaming"))
        # not tracked by this process -> a leftover, recovered
        assert client.post(f"{base}/messages", json={"content": "again"}).status_code == 200
        stuck = db.run_sync(lambda c: repo.list_messages(c, conv["id"]))[-1]
        db.run_sync(lambda c: repo.update_message(c, stuck["id"], status="streaming"))
        app.state.conversations._active.add(stuck["id"])
        busy = client.post(f"{base}/messages", json={"content": "third"})
        assert busy.status_code == 409 and busy.json()["error"]["code"] == "conversation_busy"


@respx.mock
def test_unfinished_answers_are_marked_at_startup(settings):
    respx.post(URL).mock(return_value=answer("ok"))
    app = create_app(settings)
    with TestClient(app) as client:
        conv = new(client)
        client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "q"})
        from app.db import repo

        reply = app.state.db.run_sync(lambda c: repo.list_messages(c, conv["id"]))[-1]
        app.state.db.run_sync(lambda c: repo.update_message(c, reply["id"], status="streaming"))
    with TestClient(create_app(settings)) as client:
        last = client.get(f"/api/conversations/{conv['id']}").json()["messages"][-1]
        assert last["status"] == "error" and last["error"]["code"] == "interrupted"


@respx.mock
def test_conversations_survive_a_restart_and_deleting_removes_messages(settings):
    respx.post(URL).mock(return_value=answer("ok"))
    with TestClient(create_app(settings)) as client:
        conv = new(client)
        client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "q"})
    with TestClient(create_app(settings)) as client:
        assert [c["id"] for c in client.get("/api/conversations").json()["conversations"]] == [
            conv["id"]
        ]
        assert len(client.get(f"/api/conversations/{conv['id']}").json()["messages"]) == 2
        client.delete(f"/api/conversations/{conv['id']}")
        assert client.get("/api/conversations").json()["conversations"] == []


@respx.mock
async def test_stopping_mid_answer_saves_partial_text_as_cancelled(settings):
    from app.db import repo
    from app.db.database import Database
    from app.services.chat import ChatService
    from app.services.conversations import ConversationService
    from app.services.llm import LLMClient

    respx.post(URL).mock(return_value=answer("one ", "two ", "three"))
    db = Database(settings.data_dir / "chat.db")
    db.open()
    llm = LLMClient(settings)
    service = ConversationService(db, ChatService(llm, settings), settings)
    conv = await service.create(model=None, thinking=True)
    _, events = await service.send(conv["id"], "q")
    seen = []
    async for name, _data in events:
        seen.append(name)
        if name == "content":
            break  # the browser went away after the first piece
    await events.aclose()
    reply = (await db.run(lambda c: repo.list_messages(c, conv["id"])))[-1]
    assert reply["status"] == "cancelled" and reply["content"].startswith("one")
    assert service._active == set()
    # the stopped answer is part of the next request's history
    again = await service.get(conv["id"])
    assert again["messages"][-1]["status"] == "cancelled"
    await llm.aclose()
    db.close()
