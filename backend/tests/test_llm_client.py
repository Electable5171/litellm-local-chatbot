import httpx
import pytest
import respx

from app.config import Settings
from app.errors import LLMError
from app.services.llm import LLMClient
from tests.conftest import BASE, models_response


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, litellm_base_url=BASE, litellm_api_key="sk-test", **overrides)


@respx.mock
async def test_retries_on_429_then_succeeds():
    # retry-after-ms keeps the SDK's wait to a millisecond so the test stays fast
    busy = httpx.Response(429, headers={"retry-after-ms": "1"}, json={"error": "cooldown"})
    route = respx.get(f"{BASE}/models").mock(side_effect=[busy, busy, models_response("qwen3.8")])
    llm = LLMClient(make_settings(max_retries=2))
    try:
        assert await llm.list_models() == ["qwen3.8"]
    finally:
        await llm.aclose()
    assert route.call_count == 3


@respx.mock
async def test_gives_up_after_the_configured_retries():
    busy = httpx.Response(429, headers={"retry-after-ms": "1"}, json={"error": "cooldown"})
    route = respx.get(f"{BASE}/models").mock(return_value=busy)
    llm = LLMClient(make_settings(max_retries=1))
    try:
        with pytest.raises(LLMError) as error:
            await llm.list_models()
    finally:
        await llm.aclose()
    assert error.value.code == "upstream_busy"
    assert route.call_count == 2  # first try + one retry


async def test_litellm_calls_ignore_the_system_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    llm = LLMClient(make_settings())
    try:
        assert llm._http.trust_env is False
    finally:
        await llm.aclose()
