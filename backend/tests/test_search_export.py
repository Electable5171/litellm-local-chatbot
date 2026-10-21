import json

import respx
from fastapi.testclient import TestClient

from app.db import repo
from app.main import create_app
from app.services.conversations import make_snippet
from tests.test_chat_api import URL, USAGE, chunk, sse_response


def answer(text: str, reasoning: str = ""):
    pieces = ([chunk({"reasoning_content": reasoning})] if reasoning else []) + [
        chunk({"content": text}),
        chunk(finish="stop"),
        chunk(usage=USAGE, empty_choices=True),
    ]
    return sse_response(*pieces)


def chat(client, question: str, **body) -> str:
    conv = client.post("/api/conversations", json=body).json()
    client.post(f"/api/conversations/{conv['id']}/messages", json={"content": question})
    return conv["id"]


def test_snippet_is_centred_on_the_match_and_shortened():
    text = "word " * 30 + "NEEDLE" + " tail" * 30
    snippet = make_snippet(text, "needle", width=20)
    assert "NEEDLE" in snippet and snippet.startswith("…") and snippet.endswith("…")
    assert len(snippet) < 60
    assert make_snippet("short NEEDLE text", "needle") == "short NEEDLE text"
    assert make_snippet("nothing here", "zzz") == "nothing here"


@respx.mock
def test_search_finds_titles_and_message_text_newest_first(settings):
    respx.post(URL).mock(
        side_effect=[
            answer("Paris is the capital."),
            answer("Berlin is the capital."),
            answer("Nothing relevant."),
        ]
    )
    with TestClient(create_app(settings)) as client:
        a = chat(client, "France question")
        b = chat(client, "Germany question")
        chat(client, "Unrelated")
        found = client.get("/api/conversations", params={"q": "capital"}).json()["conversations"]
        assert [c["id"] for c in found] == [b, a]
        assert "Berlin is the capital." in found[0]["snippet"]

        by_title = client.get("/api/conversations", params={"q": "GERMANY"}).json()["conversations"]
        assert [c["id"] for c in by_title] == [b]  # case-insensitive, matched in the title
        assert client.get("/api/conversations", params={"q": "zzzz"}).json() == {
            "conversations": []
        }
        everything = client.get("/api/conversations", params={"q": "  "}).json()["conversations"]
        assert len(everything) == 3 and "snippet" not in everything[0]


@respx.mock
def test_search_treats_percent_and_underscore_as_plain_text(settings):
    respx.post(URL).mock(side_effect=[answer("100% sure"), answer("a_b")])
    with TestClient(create_app(settings)) as client:
        chat(client, "q1")
        chat(client, "q2")
        percent = client.get("/api/conversations", params={"q": "%"}).json()["conversations"]
        assert len(percent) == 1 and "100% sure" in percent[0]["snippet"]
        score = client.get("/api/conversations", params={"q": "_"}).json()["conversations"]
        assert len(score) == 1 and "a_b" in score[0]["snippet"]


@respx.mock
def test_search_does_not_look_at_the_models_thinking(settings):
    respx.post(URL).mock(return_value=answer("The answer.", reasoning="secret reasoning"))
    with TestClient(create_app(settings)) as client:
        chat(client, "hello")
        assert (
            client.get("/api/conversations", params={"q": "secret"}).json()["conversations"] == []
        )


@respx.mock
def test_export_is_a_markdown_download(settings):
    respx.post(URL).mock(return_value=answer("Use `print()`.", reasoning="plan it"))
    with TestClient(create_app(settings)) as client:
        conv_id = chat(client, "How do I print?")
        r = client.get(f"/api/conversations/{conv_id}/export")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        disposition = r.headers["content-disposition"]
        assert disposition.startswith(
            'attachment; filename="how-do-i-print-'
        ) and disposition.endswith('.md"')
        text = r.text
        assert text.startswith("# How do I print?\n")
        assert "## You\n\nHow do I print?" in text
        assert "## Assistant\n\nUse `print()`." in text
        assert "plan it" not in text  # thinking is left out by default

        with_thinking = client.get(
            f"/api/conversations/{conv_id}/export", params={"thinking": "true"}
        )
        assert "<summary>Thinking</summary>\n\nplan it" in with_thinking.text
        assert client.get("/api/conversations/nope/export").status_code == 404


@respx.mock
def test_export_marks_stopped_and_failed_answers_and_lists_sources(settings):
    respx.post(URL).mock(return_value=answer("fine"))
    app = create_app(settings)
    with TestClient(app) as client:
        conv_id = chat(client, "q")
        msgs = app.state.db.run_sync(lambda c: repo.list_messages(c, conv_id))
        sources = json.dumps(
            {
                "mode": "search",
                "sources": [{"n": 1, "filename": "a.pdf", "page": 3}],
                "skipped": [],
            }
        )
        app.state.db.run_sync(
            lambda c: repo.update_message(c, msgs[-1]["id"], status="cancelled", sources=sources)
        )
        text = client.get(f"/api/conversations/{conv_id}/export").text
        assert "*(stopped)*" in text and "*Sources: [1] a.pdf p.3*" in text
        app.state.db.run_sync(
            lambda c: repo.update_message(
                c, msgs[-1]["id"], status="error", error_message="LiteLLM lost"
            )
        )
        assert "*(failed: LiteLLM lost)*" in client.get(f"/api/conversations/{conv_id}/export").text


def test_untitled_empty_chat_still_exports(settings):
    with TestClient(create_app(settings)) as client:
        conv = client.post("/api/conversations", json={}).json()
        r = client.get(f"/api/conversations/{conv['id']}/export")
        assert r.status_code == 200 and r.text.startswith("# Untitled chat")
        assert 'filename="chat-' in r.headers["content-disposition"]
