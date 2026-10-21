"""Streaming chat: build the request, stream it from LiteLLM, and turn it into events.

Events (name -> data):
  meta       {"model", "thinking", "trimmed_messages"}
  reasoning  {"delta"}   the model's thinking, streamed live
  content    {"delta"}   the answer, streamed live
  done       {"finish_reason", "usage", "latency_ms", "ttft_ms"}
  error      {"code", "message", "retry_after_s"?}   a failure after the stream has started
"""

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import anyio
import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncStream
from openai.types.chat import ChatCompletionChunk

from app.config import Settings
from app.errors import ApiError, LLMError
from app.services.llm import LLMClient, map_status_error
from app.services.thinking import ThinkingParser
from app.services.tokens import SAFETY_MARGIN, ApproxTokenCounter, TokenCounter, fit_to_budget

log = logging.getLogger("app.chat")

Event = tuple[str, dict[str, Any]]


@dataclass(frozen=True)
class ChatRequest:
    messages: list[dict[str, str]]
    model: str | None = None
    thinking: bool = True
    max_tokens: int | None = None


@dataclass(frozen=True)
class Prepared:
    model: str
    messages: list[dict[str, str]]
    thinking: bool
    max_tokens: int
    trimmed: int


def _map_error(exc: Exception, *, midstream: bool = False) -> ApiError:
    if isinstance(exc, APIStatusError):
        text = str(exc.message).lower()
        if exc.status_code == 400 and ("context length" in text or "max_model_len" in text):
            return ApiError(
                "context_too_long", "The conversation is too long for the model.", status=413
            )
        return map_status_error(exc)
    if isinstance(exc, APIConnectionError | APITimeoutError | httpx.HTTPError):
        if midstream:
            return LLMError(
                "upstream_interrupted", "The connection to LiteLLM was lost while answering.", 502
            )
        return LLMError("upstream_unreachable", "Cannot reach LiteLLM.", 502)
    return LLMError("upstream_error", "The model stream failed.", 502)


class ChatService:
    def __init__(
        self, llm: LLMClient, settings: Settings, counter: TokenCounter | None = None
    ) -> None:
        self._llm = llm
        self._settings = settings
        self._counter = counter or ApproxTokenCounter()

    def prepare(self, request: ChatRequest) -> Prepared:
        """Validate the request and trim the history to the context budget."""
        settings = self._settings
        model = request.model or settings.chat_model
        if model not in settings.model_choices:
            raise ApiError("model_not_allowed", f"Model '{model}' is not enabled.", 400)
        if request.messages[-1]["role"] != "user":
            raise ApiError("invalid_messages", "The last message must be from the user.", 400)
        max_tokens = min(
            request.max_tokens or settings.max_output_tokens, settings.max_output_tokens
        )
        budget = min(settings.context_budget_tokens, settings.max_context_tokens)
        budget -= max_tokens + SAFETY_MARGIN
        if budget < 512:
            raise ApiError(
                "config_error", "MAX_OUTPUT_TOKENS leaves no room in the context budget.", 500
            )
        messages, trimmed = fit_to_budget(request.messages, budget, self._counter)
        return Prepared(model, messages, request.thinking, max_tokens, trimmed)

    async def complete(self, model: str, messages: list[dict[str, str]], max_tokens: int) -> str:
        """One short, non-streaming answer with thinking off (used for chat titles)."""
        try:
            response = await self._llm.client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                temperature=0.3,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
        except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
            raise _map_error(exc) from exc
        return (response.choices[0].message.content or "") if response.choices else ""

    async def open_stream(self, prepared: Prepared) -> AsyncStream[ChatCompletionChunk]:
        """Start the request. Failures are raised so the caller can send a real HTTP status."""
        extra_body = (
            None if prepared.thinking else {"chat_template_kwargs": {"enable_thinking": False}}
        )
        try:
            return await self._llm.client.chat.completions.create(
                model=prepared.model,
                messages=prepared.messages,  # type: ignore[arg-type]
                max_tokens=prepared.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                extra_body=extra_body,
            )
        except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
            raise _map_error(exc) from exc

    async def events(
        self, prepared: Prepared, stream: AsyncStream[ChatCompletionChunk]
    ) -> AsyncIterator[Event]:
        """Turn the upstream stream into events. Always closes the upstream connection."""
        started = time.perf_counter()
        first_token: float | None = None
        finish_reason: str | None = None
        usage: dict[str, int] | None = None
        parser = ThinkingParser()
        yield (
            "meta",
            {
                "model": prepared.model,
                "thinking": prepared.thinking,
                "trimmed_messages": prepared.trimmed,
            },
        )
        try:
            async for chunk in stream:
                if chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                    }
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason
                extra = choice.delta.model_extra or {}
                reasoning = extra.get("reasoning_content") or extra.get("reasoning")
                for piece in parser.feed(reasoning, choice.delta.content):
                    first_token = first_token or time.perf_counter()
                    yield piece.kind, {"delta": piece.text}
            for piece in parser.flush():
                first_token = first_token or time.perf_counter()
                yield piece.kind, {"delta": piece.text}
            now = time.perf_counter()
            done = {
                "finish_reason": finish_reason,
                "usage": usage,
                "latency_ms": int((now - started) * 1000),
                "ttft_ms": int((first_token - started) * 1000) if first_token else None,
            }
            log.info(
                "chat model=%s thinking=%s trimmed=%d finish=%s usage=%s latency_ms=%d",
                prepared.model,
                prepared.thinking,
                prepared.trimmed,
                finish_reason,
                usage,
                done["latency_ms"],
            )
            yield "done", done
        except (APIError, APIConnectionError, APITimeoutError, httpx.HTTPError) as exc:
            error = _map_error(exc, midstream=True)
            log.warning("chat stream failed: %s", error.code)
            yield "error", error.body()
        except Exception:
            log.exception("chat stream crashed")
            yield "error", {"code": "internal_error", "message": "Unexpected error."}
        finally:
            # Also runs when the browser disconnects: closing the connection stops the model.
            with anyio.CancelScope(shield=True):
                await stream.close()
