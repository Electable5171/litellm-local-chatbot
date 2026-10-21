"""Saved conversations: persist every turn while it streams.

A turn is stored in this order, so a failure never leaves a half-saved exchange:

1. Validate and open the stream to LiteLLM. If this fails nothing is saved and the caller gets a
   normal HTTP error (the browser keeps the text for a retry).
2. In one transaction, save the user message and an empty assistant message (``streaming``).
3. While streaming, the answer is flushed to the database every few seconds, so a crash loses at
   most that much text. At the end the status becomes ``complete``, ``error`` or ``cancelled``;
   this also happens when the browser disconnects (the Stop button).

An assistant message still marked ``streaming`` after a restart is turned into an error at startup.
"""

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import anyio

from app.config import Settings
from app.db import documents as doc_store
from app.db import repo
from app.db.database import Database
from app.errors import ApiError
from app.services.chat import ChatRequest, ChatService, Event
from app.services.documents import document_json
from app.services.retrieval import Context, Retriever

log = logging.getLogger("app.conversations")

FLUSH_INTERVAL_S = 2.0
TITLE_MAX = 60
MAX_MESSAGE_CHARS = 200_000

# A module-level alias: inside the class, the name ``list`` is the method ``list()`` below.
DocumentList = list[dict[str, Any]]


def make_title(text: str) -> str:
    """The first line of the first question, shortened."""
    line = " ".join(text.split())
    return line if len(line) <= TITLE_MAX else line[: TITLE_MAX - 1].rstrip() + "…"


def conversation_json(row: repo.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "model": row["model"],
        "thinking": bool(row["thinking_enabled"]),
        "system_prompt": row["system_prompt"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def message_json(row: repo.Row) -> dict[str, Any]:
    usage = None
    if row["prompt_tokens"] is not None or row["completion_tokens"] is not None:
        usage = {
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
        }
    error = None
    if row["status"] == "error":
        error = {"code": row["error_code"] or "error", "message": row["error_message"] or ""}
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "reasoning": row["reasoning"] or "",
        "status": row["status"],
        "error": error,
        "finish_reason": row["finish_reason"],
        "usage": usage,
        "latency_ms": row["latency_ms"],
        "ttft_ms": row["ttft_ms"],
        "thinking_ms": row["thinking_ms"],
        "trimmed": bool(row["trimmed"]),
        "sources": _sources_json(row.get("sources")),
        "created_at": row["created_at"],
    }


def make_snippet(text: str, term: str, width: int = 60) -> str:
    """A short piece of ``text`` around the first occurrence of ``term``."""
    flat = " ".join(text.split())
    at = flat.lower().find(term.lower())
    if at < 0:
        return flat[: width * 2]
    start = max(0, at - width)
    end = min(len(flat), at + len(term) + width)
    return ("\u2026" if start else "") + flat[start:end] + ("\u2026" if end < len(flat) else "")


def _slug(title: str) -> str:
    slug = "".join(c if c.isascii() and c.isalnum() else "-" for c in title.lower())
    return "-".join(part for part in slug.split("-") if part)[:50] or "chat"


def _sources_json(raw: str | None) -> dict[str, Any] | None:
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _history(messages: list[repo.Row]) -> list[dict[str, str]]:
    """What the model should see: finished answers, and stopped ones that have some text."""
    out = []
    for m in messages:
        if m["role"] == "assistant" and (m["status"] not in ("complete", "cancelled")):
            continue
        if m["role"] == "assistant" and not m["content"]:
            continue
        out.append({"role": m["role"], "content": m["content"]})
    return out


class ConversationService:
    def __init__(
        self,
        db: Database,
        chat: ChatService,
        settings: Settings,
        retriever: Retriever | None = None,
    ) -> None:
        self._db = db
        self._retriever = retriever
        self._chat = chat
        self._settings = settings
        self._active: set[str] = set()  # assistant messages being written by this process

    # -- plain CRUD --------------------------------------------------------------------------

    async def startup(self) -> None:
        count = await self._db.run(repo.mark_interrupted)
        if count:
            log.warning("marked %d unfinished answer(s) as interrupted", count)

    async def list(self, query: str | None = None) -> list[dict[str, Any]]:
        term = (query or "").strip()
        if not term:
            return [conversation_json(r) for r in await self._db.run(repo.list_conversations)]
        found = await self._db.run(lambda c: repo.search_conversations(c, term))
        return [
            {**conversation_json(row), "snippet": make_snippet(text, term) if text else None}
            for row, text in found
        ]

    async def export_markdown(self, conversation_id: str, *, thinking: bool) -> tuple[str, str]:
        """(file name, Markdown text) for a conversation."""
        data = await self.get(conversation_id)
        started = data["created_at"][:16].replace("T", " ")
        lines = [
            f"# {data['title'] or 'Untitled chat'}",
            "",
            f"*Model {data['model']} \u00b7 started {started} UTC*",
        ]
        for m in data["messages"]:
            lines += ["", "## You" if m["role"] == "user" else "## Assistant", ""]
            if thinking and m["reasoning"]:
                lines += [
                    "<details><summary>Thinking</summary>",
                    "",
                    m["reasoning"],
                    "",
                    "</details>",
                    "",
                ]
            lines.append(m["content"] or "*(no text)*")
            if m["status"] == "cancelled":
                lines += ["", "*(stopped)*"]
            elif m["status"] == "error":
                lines += ["", f"*(failed: {(m['error'] or {}).get('message', 'error')})*"]
            used = (m.get("sources") or {}).get("sources") or []
            if used:
                names = ", ".join(
                    f"[{s['n']}] {s['filename']}" + (f" p.{s['page']}" if s["page"] else "")
                    for s in used
                )
                lines += ["", f"*Sources: {names}*"]
        stamp = data["created_at"][:10]
        return f"{_slug(data['title'])}-{stamp}.md", "\n".join(lines) + "\n"

    async def create(
        self, *, model: str | None, thinking: bool, system_prompt: str = ""
    ) -> dict[str, Any]:
        model = model or self._settings.chat_model
        if model not in self._settings.model_choices:
            raise ApiError("model_not_allowed", f"Model '{model}' is not enabled.", 400)
        row = await self._db.run(
            lambda c: repo.create_conversation(
                c, model=model, thinking=thinking, system_prompt=system_prompt
            )
        )
        return conversation_json(row)

    async def get(self, conversation_id: str) -> dict[str, Any]:
        def load(conn):
            conv = repo.get_conversation(conn, conversation_id)
            return conv, (repo.list_messages(conn, conversation_id) if conv else [])

        conv, messages = await self._db.run(load)
        if conv is None:
            raise _not_found()
        return {**conversation_json(conv), "messages": [message_json(m) for m in messages]}

    async def update(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        model: str | None = None,
        thinking: bool | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        if model is not None and model not in self._settings.model_choices:
            raise ApiError("model_not_allowed", f"Model '{model}' is not enabled.", 400)
        if title is not None:
            title = " ".join(title.split())
        row = await self._db.run(
            lambda c: repo.update_conversation(
                c,
                conversation_id,
                title=title,
                model=model,
                thinking=thinking,
                system_prompt=system_prompt,
            )
        )
        if row is None:
            raise _not_found()
        return conversation_json(row)

    async def delete(self, conversation_id: str) -> None:
        if not await self._db.run(lambda c: repo.delete_conversation(c, conversation_id)):
            raise _not_found()

    # -- attached documents ------------------------------------------------------------------

    async def documents(self, conversation_id: str) -> DocumentList:
        def load(conn):
            if repo.get_conversation(conn, conversation_id) is None:
                return None
            return doc_store.attached_documents(conn, conversation_id)

        rows = await self._db.run(load)
        if rows is None:
            raise _not_found()
        return [document_json(r) for r in rows]

    async def attach(self, conversation_id: str, document_id: str) -> DocumentList:
        def work(conn):
            if repo.get_conversation(conn, conversation_id) is None:
                raise _not_found()
            if doc_store.get_document(conn, document_id) is None:
                raise ApiError("document_not_found", "That document does not exist.", 404)
            doc_store.attach(conn, conversation_id, document_id)

        await self._db.run(work)
        return await self.documents(conversation_id)

    async def detach(self, conversation_id: str, document_id: str) -> DocumentList:
        removed = await self._db.run(lambda c: doc_store.detach(c, conversation_id, document_id))
        if not removed:
            raise ApiError("document_not_attached", "That document is not attached.", 404)
        return await self.documents(conversation_id)

    # -- turns -------------------------------------------------------------------------------

    async def send(
        self, conversation_id: str, content: str
    ) -> tuple[dict[str, Any], AsyncIterator[Event]]:
        """Add a user message and stream the answer. Returns (meta, events)."""
        if not content.strip():
            raise ApiError("invalid_messages", "The message is empty.", 400)
        if len(content) > MAX_MESSAGE_CHARS:
            raise ApiError("invalid_messages", "The message is too long.", 400)
        return await self._turn(conversation_id, content, regenerate=False)

    async def regenerate(self, conversation_id: str) -> tuple[dict[str, Any], AsyncIterator[Event]]:
        """Answer the last question again, replacing the last answer."""
        return await self._turn(conversation_id, None, regenerate=True)

    async def _turn(
        self, conversation_id: str, content: str | None, *, regenerate: bool
    ) -> tuple[dict[str, Any], AsyncIterator[Event]]:
        def load(conn):
            conv = repo.get_conversation(conn, conversation_id)
            return conv, (repo.list_messages(conn, conversation_id) if conv else [])

        conv, messages = await self._db.run(load)
        if conv is None:
            raise _not_found()
        last = messages[-1] if messages else None
        if last and last["status"] == "streaming":
            if last["id"] in self._active:
                raise ApiError("conversation_busy", "An answer is still being written.", 409)
            # Left behind by a request that never started streaming: it can never finish.
            await self._db.run(repo.mark_interrupted)
            messages = [{**m, "status": "error"} if m["id"] == last["id"] else m for m in messages]

        if regenerate:
            if not messages or messages[-1]["role"] != "assistant":
                raise ApiError("invalid_messages", "There is no answer to regenerate.", 409)
            drop = messages.pop()
            if not messages or messages[-1]["role"] != "user":
                raise ApiError("invalid_messages", "There is no question to answer.", 409)
            history = _history(messages)
        else:
            history = _history(messages) + [{"role": "user", "content": content or ""}]
            drop = None

        context: Context | None = None
        if self._retriever is not None:
            question = history[-1]["content"]
            context = await self._retriever.context_for(conversation_id, question)
            if context is not None and context.system_message:
                history = [{"role": "system", "content": context.system_message}, *history]
        if conv["system_prompt"]:
            history = [{"role": "system", "content": conv["system_prompt"]}, *history]
        prepared = self._chat.prepare(
            ChatRequest(
                messages=history, model=conv["model"], thinking=bool(conv["thinking_enabled"])
            )
        )
        stream = await self._chat.open_stream(prepared)  # raises before anything is saved

        sources = (
            {"mode": context.mode, "sources": context.sources, "skipped": context.skipped}
            if context is not None
            else None
        )

        def save(conn):
            with repo.transaction(conn):
                if drop is not None:
                    repo.delete_message(conn, drop["id"])
                    user_row = messages[-1]
                else:
                    user_row = repo.add_message(
                        conn, conversation_id, "user", content=content or ""
                    )
                reply = repo.add_message(conn, conversation_id, "assistant", status="streaming")
                if sources is not None:
                    repo.update_message(conn, reply["id"], sources=json.dumps(sources))
                title = conv["title"] or make_title(user_row["content"])
                repo.update_conversation(conn, conversation_id, title=title, touch=True)
                return user_row, reply

        try:
            user_row, reply = await self._db.run(save)
        except BaseException:
            await stream.close()
            raise
        self._active.add(reply["id"])
        meta = {
            "conversation_id": conversation_id,
            "user_message_id": user_row["id"],
            "message_id": reply["id"],
        }
        events = self._persisted(self._chat.events(prepared, stream), reply["id"], prepared.trimmed)
        return meta, _with_meta(events, meta, sources)

    async def _persisted(
        self, events: AsyncIterator[Event], message_id: str, trimmed: int
    ) -> AsyncIterator[Event]:
        content: list[str] = []
        reasoning: list[str] = []
        status = "cancelled"
        fields: dict[str, Any] = {}
        first_reasoning: float | None = None
        thinking_ms: int | None = None
        last_flush = time.monotonic()
        try:
            async for name, data in events:
                if name == "reasoning":
                    reasoning.append(data["delta"])
                    first_reasoning = first_reasoning or time.monotonic()
                elif name == "content":
                    content.append(data["delta"])
                    if first_reasoning is not None and thinking_ms is None:
                        thinking_ms = int((time.monotonic() - first_reasoning) * 1000)
                elif name == "done":
                    status = "complete"
                    usage = data.get("usage") or {}
                    fields = {
                        "finish_reason": data.get("finish_reason"),
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                        "latency_ms": data.get("latency_ms"),
                        "ttft_ms": data.get("ttft_ms"),
                    }
                elif name == "error":
                    status = "error"
                    fields = {
                        "error_code": data.get("code"),
                        "error_message": data.get("message"),
                    }
                yield name, data
                if time.monotonic() - last_flush >= FLUSH_INTERVAL_S and status == "cancelled":
                    last_flush = time.monotonic()
                    await self._db.run(
                        lambda c: repo.update_message(
                            c,
                            message_id,
                            content="".join(content),
                            reasoning="".join(reasoning),
                        )
                    )
        finally:
            if first_reasoning is not None and thinking_ms is None:
                thinking_ms = int((time.monotonic() - first_reasoning) * 1000)
            final = {
                "content": "".join(content),
                "reasoning": "".join(reasoning),
                "status": status,
                "thinking_ms": thinking_ms,
                "trimmed": int(trimmed > 0),
                **fields,
            }
            with anyio.CancelScope(shield=True):  # also when the browser disconnects
                aclose = getattr(events, "aclose", None)
                if aclose:
                    await aclose()  # closes the upstream connection, which stops the model
                try:
                    await self._db.run(lambda c: repo.update_message(c, message_id, **final))
                except Exception:
                    log.exception("could not save the answer %s", message_id)
                finally:
                    self._active.discard(message_id)


async def _with_meta(
    events: AsyncIterator[Event], extra: dict[str, Any], sources: dict[str, Any] | None
) -> AsyncIterator[Event]:
    try:
        async for name, data in events:
            if name == "meta":
                yield name, {**data, **extra}
                if sources is not None:
                    yield "sources", sources
            else:
                yield name, data
    finally:
        aclose = getattr(events, "aclose", None)
        if aclose:
            await aclose()


def _not_found() -> ApiError:
    return ApiError("conversation_not_found", "That conversation does not exist.", 404)
