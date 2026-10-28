import json
from urllib.parse import quote

import httpx
import respx
from fastapi.testclient import TestClient

from app.db import repo
from app.main import create_app
from app.services.tokens import ApproxTokenCounter
from tests.conftest import BASE
from tests.test_chat_api import URL, USAGE, chunk, sse_response

COUNT = ApproxTokenCounter().count


def answer(text: str):
    return sse_response(
        chunk({"content": text}), chunk(finish="stop"), chunk(usage=USAGE, empty_choices=True)
    )


def usage(client, conv_id):
    r = client.get(f"/api/conversations/{conv_id}/context")
    assert r.status_code == 200
    return r.json()


def small_limits(settings, **extra):
    # budget = 1400 - 300 reserved - 256 margin = 844 tokens for the request
    return settings.model_copy(
        update={"context_budget_tokens": 1400, "max_output_tokens": 300, **extra}
    )


def test_an_empty_chat_uses_nothing_and_reports_the_limits(settings):
    with TestClient(create_app(settings)) as client:
        conv = client.post("/api/conversations", json={}).json()
        data = usage(client, conv["id"])
    assert data["used"] == 0 and data["percent"] == 0 and data["messages"] == 0
    assert data["limit"] == 32_768 and data["reserved_for_answer"] == 8192 + 256
    assert data["budget"] == 32_768 - 8192 - 256 and data["would_trim"] == 0


@respx.mock
def test_messages_and_instructions_are_counted_like_the_trimming_counts_them(settings):
    respx.post(URL).mock(return_value=answer("The answer text."))
    with TestClient(create_app(settings)) as client:
        conv = client.post("/api/conversations", json={"system_prompt": "Be brief."}).json()
        client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "A question?"})
        data = usage(client, conv["id"])
    expected_messages = (COUNT("A question?") + 4) + (COUNT("The answer text.") + 4)
    assert data["parts"] == {
        "instructions": COUNT("Be brief.") + 4,
        "documents": 0,
        "messages": expected_messages,
    }
    assert data["used"] == data["parts"]["instructions"] + expected_messages
    assert data["messages"] == 2 and data["would_trim"] == 0
    assert data["percent"] == round(100 * data["used"] / data["budget"])


@respx.mock
def test_failed_answers_are_not_counted_and_stopped_ones_with_text_are(settings):
    respx.post(URL).mock(side_effect=[answer("fine " * 20), answer("partial " * 20)])
    app = create_app(settings)
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        base = f"/api/conversations/{conv['id']}"
        client.post(f"{base}/messages", json={"content": "q1"})
        client.post(f"{base}/messages", json={"content": "q2"})
        msgs = app.state.db.run_sync(lambda c: repo.list_messages(c, conv["id"]))
        before = usage(client, conv["id"])
        app.state.db.run_sync(lambda c: repo.update_message(c, msgs[-1]["id"], status="error"))
        after = usage(client, conv["id"])
        assert after["messages"] == before["messages"] - 1
        assert after["used"] < before["used"]
        app.state.db.run_sync(lambda c: repo.update_message(c, msgs[-1]["id"], status="cancelled"))
        assert usage(client, conv["id"]) == before  # stopped answers are sent to the model


@respx.mock
def test_it_says_how_many_old_messages_the_next_request_would_drop(settings):
    long_answer = "word " * 150  # about 250 tokens each
    respx.post(URL).mock(side_effect=[answer(long_answer)] * 4)
    with TestClient(create_app(small_limits(settings))) as client:
        conv = client.post("/api/conversations", json={}).json()
        base = f"/api/conversations/{conv['id']}"
        trimmed = []
        for i in range(4):
            client.post(f"{base}/messages", json={"content": f"question number {i}"})
            trimmed.append(usage(client, conv["id"])["would_trim"])
        data = usage(client, conv["id"])
    assert trimmed[0] == 0 and trimmed[-1] > 0  # it fills up, then old messages would go
    assert trimmed == sorted(trimmed)
    assert data["budget"] == 844 and data["percent"] > 100 and data["would_trim"] == trimmed[-1]


@respx.mock
def test_attached_documents_count_up_to_the_document_budget(settings):
    def embed(request):
        body = json.loads(request.content)
        rows = [
            {"object": "embedding", "index": i, "embedding": [1.0, 0.0]}
            for i, _ in enumerate(body["input"])
        ]
        return httpx.Response(200, json={"object": "list", "data": rows, "model": "m", "usage": {}})

    respx.post(f"{BASE}/embeddings").mock(side_effect=embed)
    settings = settings.model_copy(update={"rag_context_tokens": 500, "chunk_tokens": 100})
    with TestClient(create_app(settings)) as client:
        conv = client.post("/api/conversations", json={}).json()
        text = ("A sentence about nothing in particular. " * 400).encode()
        doc = client.post(
            "/api/documents",
            content=text,
            headers={"content-type": "application/octet-stream", "x-filename": quote("big.txt")},
        ).json()
        client.portal.call(client.app.state.documents.wait_idle)
        assert usage(client, conv["id"])["parts"]["documents"] == 0  # not attached yet
        client.post(f"/api/conversations/{conv['id']}/documents/{doc['id']}")
        docs = usage(client, conv["id"])["parts"]["documents"]
    assert 500 <= docs <= 500 + 200  # the budget plus the instruction text, never the whole file


def test_unknown_conversation_is_a_404(settings):
    with TestClient(create_app(settings)) as client:
        r = client.get("/api/conversations/nope/context")
    assert r.status_code == 404 and r.json()["error"]["code"] == "conversation_not_found"
