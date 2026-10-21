"""LiteLLM client: the OpenAI SDK pointed at the on-prem proxy.

Two rules baked in here:
* ``trust_env=False``: calls to LiteLLM never go through the Windows or corporate web proxy,
  whatever HTTP_PROXY / the system proxy says (it differs by network location).
* The SDK retries 429 / 5xx / connection errors with backoff (the model is shared, and LiteLLM
  puts it on a short cooldown after an upstream error).
"""

import time
from dataclasses import dataclass

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.config import Settings
from app.errors import LLMError


@dataclass(frozen=True)
class Probe:
    """Result of one reachability check."""

    reachable: bool
    latency_ms: int | None
    model_ids: tuple[str, ...]
    error: str | None
    checked_at: float


def map_status_error(exc: APIStatusError) -> LLMError:
    status = exc.status_code
    if status in (401, 403):
        return LLMError(
            "upstream_auth", "LiteLLM rejected the API key (check LITELLM_API_KEY).", 502
        )
    if status == 429:
        return LLMError(
            "upstream_busy", "The model is busy. Try again in a few seconds.", 503, retry_after_s=5
        )
    if status >= 500:
        return LLMError("upstream_error", f"LiteLLM returned an error ({status}).", 502)
    return LLMError("upstream_rejected", f"LiteLLM rejected the request ({status}).", 502)


class LLMClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(
            trust_env=False,
            timeout=httpx.Timeout(settings.request_timeout_s, connect=settings.connect_timeout_s),
        )
        self.client = AsyncOpenAI(
            api_key=settings.litellm_api_key.get_secret_value(),
            base_url=settings.litellm_base_url,
            http_client=self._http,
            max_retries=settings.max_retries,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def list_models(self) -> list[str]:
        """Model ids this key may use. Raises LLMError with a user-readable code."""
        try:
            page = await self.client.models.list()
        except (APIConnectionError, APITimeoutError) as exc:
            raise LLMError("upstream_unreachable", "Cannot reach LiteLLM.", 502) from exc
        except APIStatusError as exc:
            raise map_status_error(exc) from exc
        return [m.id for m in page.data]

    async def probe(self) -> Probe:
        """One quick check (short timeout, no retries) used by the health endpoint."""
        start = time.perf_counter()
        quick = self.client.with_options(max_retries=0, timeout=5.0)
        try:
            page = await quick.models.list()
        except (APIConnectionError, APITimeoutError):
            return Probe(False, None, (), "Cannot reach LiteLLM.", time.time())
        except APIStatusError as exc:
            return Probe(False, None, (), map_status_error(exc).message, time.time())
        latency = int((time.perf_counter() - start) * 1000)
        return Probe(True, latency, tuple(m.id for m in page.data), None, time.time())
