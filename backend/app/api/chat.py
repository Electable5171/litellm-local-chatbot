import json
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.chat import ChatRequest, Event

router = APIRouter(prefix="/api")


class MessageIn(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=200_000)


class ChatIn(BaseModel):
    messages: list[MessageIn] = Field(min_length=1, max_length=200)
    model: str | None = None
    thinking: bool = True
    max_tokens: int | None = Field(default=None, ge=1, le=262_144)


async def _sse(events: AsyncIterator[Event]) -> AsyncGenerator[str, None]:
    try:
        async for name, data in events:
            yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    finally:
        aclose = getattr(events, "aclose", None)
        if aclose:
            await aclose()


@router.post("/chat")
async def chat(body: ChatIn, request: Request) -> StreamingResponse:
    """Stream one answer as server-sent events. The conversation is sent by the caller."""
    service = request.app.state.chat
    prepared = service.prepare(
        ChatRequest(
            messages=[m.model_dump() for m in body.messages],
            model=body.model,
            thinking=body.thinking,
            max_tokens=body.max_tokens,
        )
    )
    stream = await service.open_stream(prepared)  # raises a clean error before streaming starts
    return StreamingResponse(
        _sse(service.events(prepared, stream)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
