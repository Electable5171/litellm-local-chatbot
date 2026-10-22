import json
from pathlib import Path

import respx
from fastapi.testclient import TestClient

import app.db.database as dbmod
from app.db.database import Database
from app.main import create_app
from tests.test_chat_api import URL, USAGE, chunk, sse_response


def test_starter_presets_are_there_in_order(settings):
    with TestClient(create_app(settings)) as client:
        presets = client.get("/api/presets").json()["presets"]
    assert [p["name"] for p in presets] == [
        "Concise",
        "Plain language",
        "Step by step",
        "Code helper",
        "Critical reviewer",
    ]
    assert all(p["content"] for p in presets)


def test_create_edit_and_delete(settings):
    with TestClient(create_app(settings)) as client:
        made = client.post("/api/presets", json={"name": "  My   style ", "content": "Be kind."})
        assert made.status_code == 201 and made.json()["name"] == "My style"
        pid = made.json()["id"]
        assert client.get("/api/presets").json()["presets"][-1]["id"] == pid  # new ones go last

        renamed = client.patch(f"/api/presets/{pid}", json={"name": "Kind"}).json()
        assert (renamed["name"], renamed["content"]) == ("Kind", "Be kind.")
        edited = client.patch(f"/api/presets/{pid}", json={"content": "Be very kind."}).json()
        assert (edited["name"], edited["content"]) == ("Kind", "Be very kind.")

        assert client.delete(f"/api/presets/{pid}").status_code == 204
        assert client.delete(f"/api/presets/{pid}").status_code == 404
        assert client.patch(f"/api/presets/{pid}", json={"name": "x"}).status_code == 404


def test_validation(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/presets", json={"name": "", "content": "x"}).status_code == 422
        assert client.post("/api/presets", json={"name": "x", "content": ""}).status_code == 422
        assert (
            client.post("/api/presets", json={"name": "x" * 61, "content": "x"}).status_code == 422
        )
        blank = client.post("/api/presets", json={"name": "   ", "content": "x"})
        assert blank.status_code == 400 and blank.json()["error"]["code"] == "invalid_preset"
        blank_text = client.post("/api/presets", json={"name": "x", "content": "  \n "})
        assert blank_text.status_code == 400
        pid = client.get("/api/presets").json()["presets"][0]["id"]
        assert client.patch(f"/api/presets/{pid}", json={"name": "  "}).status_code == 400
        assert client.patch(f"/api/presets/{pid}", json={"content": " "}).status_code == 400


@respx.mock
def test_a_chat_keeps_the_text_it_was_given_when_the_preset_changes_or_goes(settings):
    route = respx.post(URL).mock(
        return_value=sse_response(
            chunk({"content": "ok"}), chunk(finish="stop"), chunk(usage=USAGE, empty_choices=True)
        )
    )
    with TestClient(create_app(settings)) as client:
        preset = client.get("/api/presets").json()["presets"][0]
        conv = client.post("/api/conversations", json={"system_prompt": preset["content"]}).json()
        client.patch(f"/api/presets/{preset['id']}", json={"content": "Something else entirely."})
        client.delete(f"/api/presets/{preset['id']}")
        client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "hi"})
        assert (
            client.get(f"/api/conversations/{conv['id']}").json()["system_prompt"]
            == preset["content"]
        )
    sent = json.loads(route.calls[0].request.content)["messages"]
    assert sent[0] == {"role": "system", "content": preset["content"]}


def test_upgrading_an_existing_database_adds_the_starters_and_keeps_data(
    tmp_path: Path, monkeypatch
):
    path = tmp_path / "chat.db"
    real = dbmod._migrations()
    monkeypatch.setattr(dbmod, "_migrations", lambda: [m for m in real if m[0] < 5])
    old = Database(path)
    old.open()
    old.run_sync(
        lambda c: c.execute(
            "INSERT INTO conversations"
            " (id, title, model, thinking_enabled, system_prompt, created_at, updated_at,"
            " title_source) VALUES ('c1', 'Keep me', 'qwen3.8', 1, '', 'x', 'x', 'user')"
        )
    )
    old.close()
    monkeypatch.setattr(dbmod, "_migrations", lambda: real)
    new = Database(path)
    new.open()
    assert (
        new.run_sync(lambda c: c.execute("SELECT COUNT(*) FROM prompt_presets").fetchone()[0]) == 5
    )
    assert (
        new.run_sync(lambda c: c.execute("SELECT title FROM conversations").fetchone()[0])
        == "Keep me"
    )
    assert list((tmp_path / "backups").glob("chat-*-v4.db"))  # backed up before upgrading
    new.close()
