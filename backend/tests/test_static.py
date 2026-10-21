import respx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import BASE, models_response


@respx.mock
def test_every_response_carries_the_browser_safety_headers(settings):
    respx.get(f"{BASE}/models").mock(return_value=models_response("qwen3.8"))
    with TestClient(create_app(settings)) as client:
        for response in (client.get("/api/health"), client.get("/api/nothing-here")):
            policy = response.headers["content-security-policy"]
            assert "default-src 'self'" in policy
            assert "script-src 'self'" in policy
            assert "img-src 'self' data:" in policy
            assert "frame-ancestors 'none'" in policy
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "no-referrer"


def test_the_built_frontend_is_served_from_the_same_origin(settings, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Local Chat</title>")
    (dist / "assets" / "app.js").write_text("console.log('ok')")
    monkeypatch.setattr("app.main.FRONTEND_DIST", dist)
    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        script = client.get("/assets/app.js")
        api = client.get("/api/nothing-here")
    assert page.status_code == 200 and "Local Chat" in page.text
    assert "content-security-policy" in page.headers
    assert script.status_code == 200
    assert api.status_code == 404  # unknown API paths are not swallowed by the page


def test_without_a_build_only_the_api_is_available(settings, monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.FRONTEND_DIST", tmp_path / "missing")
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 404
