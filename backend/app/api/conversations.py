from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.chat import sse
from app.services.conversations import ConversationService

router = APIRouter(prefix="/api/conversations")


class CreateIn(BaseModel):
    model: str | None = None
    thinking: bool = True
    system_prompt: str = Field(default="", max_length=20_000)


class UpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = None
    thinking: bool | None = None
    system_prompt: str | None = Field(default=None, max_length=20_000)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)


def _service(request: Request) -> ConversationService:
    return request.app.state.conversations


def _stream(events) -> StreamingResponse:
    return StreamingResponse(
        sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("")
async def list_conversations(
    request: Request, q: str | None = Query(default=None, max_length=200)
) -> dict[str, Any]:
    """All conversations, newest first; with ``q``, only those containing the text."""
    return {"conversations": await _service(request).list(q)}


@router.post("", status_code=201)
async def create_conversation(body: CreateIn, request: Request) -> dict[str, Any]:
    return await _service(request).create(
        model=body.model, thinking=body.thinking, system_prompt=body.system_prompt
    )


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).get(conversation_id)


@router.get("/{conversation_id}/context")
async def context_usage(conversation_id: str, request: Request) -> dict[str, Any]:
    """How full the next request to the model would be, and how many old messages would go."""
    return await _service(request).context_usage(conversation_id)


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: str, request: Request, thinking: bool = False
) -> Response:
    """Download the conversation as a Markdown file (add ``?thinking=true`` to include thinking)."""
    name, text = await _service(request).export_markdown(conversation_id, thinking=thinking)
    return Response(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: str, body: UpdateIn, request: Request
) -> dict[str, Any]:
    return await _service(request).update(conversation_id, **body.model_dump(exclude_unset=True))


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request) -> Response:
    await _service(request).delete(conversation_id)
    return Response(status_code=204)


@router.post("/{conversation_id}/messages")
async def send_message(conversation_id: str, body: MessageIn, request: Request):
    """Save the question, then stream and save the answer (server-sent events)."""
    _, events = await _service(request).send(conversation_id, body.content)
    return _stream(events)


@router.post("/{conversation_id}/messages/{message_id}/edit")
async def edit_message(conversation_id: str, message_id: str, body: MessageIn, request: Request):
    """Replace one of your messages and everything after it, then answer the new text (SSE)."""
    _, events = await _service(request).edit(conversation_id, message_id, body.content)
    return _stream(events)


@router.post("/{conversation_id}/regenerate")
async def regenerate(conversation_id: str, request: Request):
    """Answer the last question again, replacing the last answer."""
    _, events = await _service(request).regenerate(conversation_id)
    return _stream(events)


@router.get("/{conversation_id}/documents")
async def list_attached(conversation_id: str, request: Request) -> dict[str, Any]:
    return {"documents": await _service(request).documents(conversation_id)}


@router.post("/{conversation_id}/documents/{document_id}")
async def attach_document(
    conversation_id: str, document_id: str, request: Request
) -> dict[str, Any]:
    """Search this document when answering questions in this conversation."""
    return {"documents": await _service(request).attach(conversation_id, document_id)}


@router.delete("/{conversation_id}/documents/{document_id}")
async def detach_document(
    conversation_id: str, document_id: str, request: Request
) -> dict[str, Any]:
    return {"documents": await _service(request).detach(conversation_id, document_id)}
