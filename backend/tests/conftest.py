import httpx
import pytest

from app.config import Settings

BASE = "http://litellm.test:4000/v1"


def models_payload(*ids: str) -> dict:
    return {
        "object": "list",
        "data": [{"id": i, "object": "model", "created": 0, "owned_by": "test"} for i in ids],
    }


def models_response(*ids: str) -> httpx.Response:
    return httpx.Response(200, json=models_payload(*ids))


@pytest.fixture
def settings(tmp_path):
    # _env_file=None: tests never read a developer's real .env
    return Settings(
        _env_file=None,
        litellm_base_url=BASE,
        litellm_api_key="sk-test-secret",
        data_dir=tmp_path / "data",
        max_retries=0,
        health_cache_s=60,
        allowed_models="qwen3.8,nemotron-nano,gpt-oss",
    )
