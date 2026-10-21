import json
from urllib.parse import quote

import httpx
import respx
from fastapi.testclient import TestClient

from app.db import documents as store
from app.main import create_app
from app.services.embeddings import normalise, unpack
from tests.conftest import BASE
from tests.files import make_docx, make_pdf

URL = f"{BASE}/embeddings"
OCTET = {"content-type": "application/octet-stream"}


def embed_ok(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    data = [
        {"object": "embedding", "index": i, "embedding": [float(len(t) % 7 + 1), 2.0, 3.0, 4.0]}
        for i, t in enumerate(body["input"])
    ]
    return httpx.Response(
        200, json={"object": "list", "data": data, "model": body["model"], "usage": {}}
    )


def upload(client, name: str, data: bytes, headers=OCTET):
    return client.post(
        "/api/documents", content=data, headers={**headers, "x-filename": quote(name)}
    )


def wait(client):
    client.portal.call(client.app.state.documents.wait_idle)


def test_upload_embeds_in_background_and_reports_progress(settings):
    with respx.mock:
        route = respx.post(URL).mock(side_effect=embed_ok)
        with TestClient(create_app(settings)) as client:
            r = upload(client, "notes.txt", b"Hello world. " * 10)
            assert r.status_code == 201
            doc = r.json()
            assert doc["filename"] == "notes.txt" and doc["chunk_count"] == 1
            wait(client)
            got = client.get(f"/api/documents/{doc['id']}").json()
            assert got["status"] == "ready" and got["embedded_count"] == 1
            assert [d["id"] for d in client.get("/api/documents").json()["documents"]] == [
                doc["id"]
            ]
        body = json.loads(route.calls[0].request.content)
        assert body["model"] == "llama-nemotron-embed-1b-v2"
        assert body["input_type"] == "passage"


def test_vectors_are_stored_normalised_with_model_and_dimension(settings):
    with respx.mock:
        respx.post(URL).mock(side_effect=embed_ok)
        app = create_app(settings)
        with TestClient(app) as client:
            doc = upload(client, "a.txt", b"some text here").json()
            wait(client)
            row = app.state.db.run_sync(lambda c: store.get_document(c, doc["id"]))
            blob = app.state.db.run_sync(
                lambda c: c.execute("SELECT embedding FROM chunks").fetchone()[0]
            )
    assert (row["embedding_model"], row["embedding_dim"]) == ("llama-nemotron-embed-1b-v2", 4)
    expected = normalise([float(len("some text here") % 7 + 1), 2.0, 3.0, 4.0])
    assert all(abs(a - b) < 1e-6 for a, b in zip(unpack(blob), expected, strict=True))


def test_embeddings_are_requested_in_batches_one_at_a_time(settings):
    settings = settings.model_copy(update={"embedding_batch_size": 2, "chunk_tokens": 100})
    text = "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(7)).encode()
    with respx.mock:
        route = respx.post(URL).mock(side_effect=embed_ok)
        with TestClient(create_app(settings)) as client:
            doc = upload(client, "long.txt", text).json()
            assert doc["chunk_count"] >= 5
            wait(client)
            assert client.get(f"/api/documents/{doc['id']}").json()["status"] == "ready"
        sizes = [len(json.loads(c.request.content)["input"]) for c in route.calls]
    assert max(sizes) == 2 and sum(sizes) == doc["chunk_count"]


def test_pdf_and_docx_uploads(settings):
    with respx.mock:
        respx.post(URL).mock(side_effect=embed_ok)
        with TestClient(create_app(settings)) as client:
            pdf = upload(client, "r.pdf", make_pdf(["Page one", "Page two"])).json()
            docx = upload(client, "m.docx", make_docx(["Hello", "World"])).json()
            wait(client)
            assert pdf["page_count"] == 2 and docx["mime"].endswith("wordprocessingml.document")
            assert {d["status"] for d in client.get("/api/documents").json()["documents"]} == {
                "ready"
            }


def test_same_file_twice_is_stored_once(settings):
    with respx.mock:
        route = respx.post(URL).mock(side_effect=embed_ok)
        with TestClient(create_app(settings)) as client:
            first = upload(client, "a.txt", b"same content")
            wait(client)
            second = upload(client, "copy of a.txt", b"same content")
            assert (first.status_code, second.status_code) == (201, 200)
            assert second.json()["id"] == first.json()["id"]
            assert len(client.get("/api/documents").json()["documents"]) == 1
        assert len(route.calls) == 1


def test_bad_uploads_are_refused_with_clear_errors(settings):
    settings = settings.model_copy(update={"max_upload_mb": 1})
    with TestClient(create_app(settings)) as client:

        def code(r):
            return r.status_code, r.json()["error"]["code"]

        assert code(upload(client, "a.xlsx", b"PKxx")) == (415, "unsupported_file")
        assert code(upload(client, "a.txt", b"")) == (400, "invalid_file")
        assert code(upload(client, "a.txt", b"x" * (1024 * 1024 + 1))) == (413, "file_too_large")
        assert code(upload(client, "a.pdf", b"not a pdf")) == (422, "unreadable_file")
        assert code(upload(client, "a.pdf", make_pdf([""]))) == (422, "no_text")
        no_name = client.post("/api/documents", content=b"x", headers=OCTET)
        assert code(no_name) == (400, "invalid_file")
        assert client.get("/api/documents").json() == {"documents": []}


def test_only_octet_stream_is_accepted_so_other_web_pages_cannot_upload(settings):
    with TestClient(create_app(settings)) as client:
        for kind in ("text/plain", "multipart/form-data", "application/json", ""):
            r = client.post(
                "/api/documents",
                content=b"hello",
                headers={"content-type": kind, "x-filename": "a.txt"},
            )
            assert r.status_code == 415, kind


def test_embedding_failure_marks_the_document_and_a_new_upload_resumes(settings):
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(401, json={"error": {"message": "key"}}))
        with TestClient(create_app(settings)) as client:
            doc = upload(client, "a.txt", b"hello there").json()
            wait(client)
            failed = client.get(f"/api/documents/{doc['id']}").json()
            assert failed["status"] == "error" and "API key" in failed["error"]
            assert failed["chunk_count"] == 1 and failed["embedded_count"] == 0

            respx.post(URL).mock(side_effect=embed_ok)
            again = upload(client, "a.txt", b"hello there")
            assert again.status_code == 200 and again.json()["id"] == doc["id"]
            wait(client)
            assert client.get(f"/api/documents/{doc['id']}").json()["status"] == "ready"


def test_unfinished_documents_continue_after_a_restart(settings):
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(503, json={"error": {"message": "x"}}))
        app = create_app(settings)
        with TestClient(app) as client:
            doc = upload(client, "a.txt", b"hello there").json()
            wait(client)
            app.state.db.run_sync(lambda c: store.set_status(c, doc["id"], "processing"))
        respx.post(URL).mock(side_effect=embed_ok)
        with TestClient(create_app(settings)) as client:
            wait(client)
            assert client.get(f"/api/documents/{doc['id']}").json()["status"] == "ready"


def test_delete_removes_document_and_chunks(settings):
    with respx.mock:
        respx.post(URL).mock(side_effect=embed_ok)
        app = create_app(settings)
        with TestClient(app) as client:
            doc = upload(client, "a.txt", b"hello there").json()
            wait(client)
            assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
            assert client.delete(f"/api/documents/{doc['id']}").status_code == 404
            assert client.get(f"/api/documents/{doc['id']}").status_code == 404
            count = app.state.db.run_sync(
                lambda c: c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            )
            assert count == 0
