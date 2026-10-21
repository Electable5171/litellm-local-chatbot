import httpx
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import BASE, models_response


@respx.mock
def test_health_ok(settings):
    route = respx.get(f"{BASE}/models").mock(return_value=models_response("qwen3.8", "gpt-oss"))
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["litellm"]["reachable"] is True
    assert body["chat_model"] == {"id": "qwen3.8", "available": True}
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-test-secret"


@respx.mock
def test_health_is_degraded_but_still_200_when_litellm_is_down(settings):
    respx.get(f"{BASE}/models").mock(side_effect=httpx.ConnectError("down"))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["litellm"]["reachable"] is False
    assert body["chat_model"]["available"] is None


@respx.mock
def test_health_is_degraded_when_the_chat_model_is_missing(settings):
    respx.get(f"{BASE}/models").mock(return_value=models_response("gpt-oss"))
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["chat_model"]["available"] is False


@respx.mock
def test_health_result_is_cached(settings):
    route = respx.get(f"{BASE}/models").mock(return_value=models_response("qwen3.8"))
    with TestClient(create_app(settings)) as client:
        for _ in range(3):
            client.get("/api/health")
    assert route.call_count == 1


@respx.mock
def test_models_lists_allowed_models_with_availability(settings):
    respx.get(f"{BASE}/models").mock(return_value=models_response("qwen3.8", "gpt-oss", "other"))
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/models").json()
    assert body["default"] == "qwen3.8"
    assert body["models"] == [
        {"id": "qwen3.8", "available": True},
        {"id": "nemotron-nano", "available": False},
        {"id": "gpt-oss", "available": True},
    ]


@respx.mock
def test_models_maps_an_auth_failure_to_a_clean_error(settings):
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/models")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_auth"
    assert "sk-test-secret" not in response.text


@respx.mock
def test_models_maps_429_to_503_with_a_retry_hint(settings):
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(429, json={"error": "cooldown"}))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/models")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "upstream_busy"
    assert error["retry_after_s"] == 5


@respx.mock
def test_models_maps_a_connection_failure(settings):
    respx.get(f"{BASE}/models").mock(side_effect=httpx.ConnectError("down"))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/models")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unreachable"


@respx.mock
def test_request_id_header_is_set_and_sanitised(settings):
    respx.get(f"{BASE}/models").mock(return_value=models_response("qwen3.8"))
    with TestClient(create_app(settings)) as client:
        generated = client.get("/api/health").headers["x-request-id"]
        echoed = client.get("/api/health", headers={"x-request-id": "abc-123_DEF"})
        cleaned = client.get("/api/health", headers={"x-request-id": "a b;c<d>"})
    assert len(generated) == 12
    assert echoed.headers["x-request-id"] == "abc-123_DEF"
    assert cleaned.headers["x-request-id"] == "abcd"
