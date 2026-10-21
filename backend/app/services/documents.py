"""Uploaded documents: read, split, embed in the background, list, delete.

Upload does the cheap, checkable work at once (type, size, text extraction, chunking), so a bad
file is refused with a clear message. Embedding takes minutes for a large file, so it runs in the
background, one document and one request at a time (the model is shared), and the list shows
progress. If the app stops in the middle, the next start continues with the chunks that still
have no embedding.
"""

import asyncio
import hashlib
import logging
from typing import Any

from app.config import Settings
from app.db import documents as store
from app.db.database import Database
from app.errors import ApiError
from app.services.chunking import chunk_pages
from app.services.embeddings import Embedder, pack
from app.services.extract import extract

log = logging.getLogger("app.documents")


def document_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "mime": row["mime"],
        "size_bytes": row["size_bytes"],
        "status": row["status"],
        "error": row["error"],
        "page_count": row["page_count"],
        "chunk_count": row["chunk_count"],
        "embedded_count": row.get(
            "embedded_count", row["chunk_count"] if row["status"] == "ready" else 0
        ),
        "created_at": row["created_at"],
    }


class DocumentService:
    def __init__(self, db: Database, embedder: Embedder, settings: Settings) -> None:
        self._db = db
        self._embedder = embedder
        self._settings = settings
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._gate = asyncio.Semaphore(1)  # one document at a time

    @property
    def max_bytes(self) -> int:
        return self._settings.max_upload_mb * 1024 * 1024

    # -- lifecycle ---------------------------------------------------------------------------

    async def startup(self) -> None:
        for document_id in await self._db.run(store.processing_ids):
            self._start(document_id)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def wait_idle(self) -> None:
        """Wait until all background work is done (used by tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    # -- API ---------------------------------------------------------------------------------

    async def list(self) -> list[dict[str, Any]]:
        return [document_json(r) for r in await self._db.run(store.list_documents)]

    async def get(self, document_id: str) -> dict[str, Any]:
        rows = await self._db.run(store.list_documents)
        for row in rows:
            if row["id"] == document_id:
                return document_json(row)
        raise _not_found()

    async def delete(self, document_id: str) -> None:
        task = self._tasks.pop(document_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if not await self._db.run(lambda c: store.delete_document(c, document_id)):
            raise _not_found()

    async def upload(self, filename: str, data: bytes) -> tuple[dict[str, Any], bool]:
        """Returns (document, created). The same file uploaded twice is stored once."""
        if not data:
            raise ApiError("invalid_file", "The file is empty.", 400)
        if len(data) > self.max_bytes:
            raise ApiError(
                "file_too_large",
                f"The file is larger than {self._settings.max_upload_mb} MB.",
                413,
            )
        filename = " ".join(filename.replace("\\", "/").rsplit("/", 1)[-1].split())[:200]
        digest = hashlib.sha256(data).hexdigest()
        existing = await self._db.run(lambda c: store.get_by_sha256(c, digest))
        if existing:
            if existing["status"] == "error":  # try again, keeping the chunks already stored
                await self._db.run(lambda c: store.set_status(c, existing["id"], "processing"))
                self._start(existing["id"])
            return await self.get(existing["id"]), False

        settings = self._settings

        def prepare():
            extracted = extract(filename, data, max_pdf_pages=settings.max_pdf_pages)
            chunks = chunk_pages(
                extracted.pages,
                target_tokens=settings.chunk_tokens,
                overlap_tokens=settings.chunk_overlap_tokens,
            )
            return extracted, chunks

        extracted, chunks = await asyncio.to_thread(prepare)
        if len(chunks) > settings.max_chunks_per_document:
            raise ApiError(
                "document_too_large",
                f"The document is too long ({len(chunks)} parts; the limit is "
                f"{settings.max_chunks_per_document}).",
                413,
            )
        row = await self._db.run(
            lambda c: store.create_document(
                c,
                filename=filename,
                sha256=digest,
                mime=extracted.mime,
                size_bytes=len(data),
                page_count=extracted.page_count,
                chunks=[(k.ordinal, k.page, k.text, k.tokens) for k in chunks],
            )
        )
        self._start(row["id"])
        return await self.get(row["id"]), True

    # -- background embedding ----------------------------------------------------------------

    def _start(self, document_id: str) -> None:
        if document_id in self._tasks:
            return
        task = asyncio.create_task(self._ingest(document_id))
        self._tasks[document_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(document_id, None))

    async def _ingest(self, document_id: str) -> None:
        batch = self._settings.embedding_batch_size
        try:
            async with self._gate:
                dim: int | None = None
                while True:
                    pending = await self._db.run(
                        lambda c: store.pending_chunks(c, document_id, batch)
                    )
                    if not pending:
                        break
                    vectors = await self._embedder.embed([p["text"] for p in pending], "passage")
                    dim = len(vectors[0])
                    rows = [(pack(v), p["id"]) for v, p in zip(vectors, pending, strict=True)]
                    await self._db.run(lambda c, rows=rows: store.save_embeddings(c, rows))
                await self._db.run(
                    lambda c: store.set_status(
                        c,
                        document_id,
                        "ready",
                        embedding_model=self._embedder.model,
                        embedding_dim=dim,
                    )
                )
                log.info("document %s is ready", document_id)
        except asyncio.CancelledError:
            raise
        except ApiError as exc:
            log.warning("embedding document %s failed: %s", document_id, exc.code)
            await self._fail(document_id, exc.message)
        except Exception:
            log.exception("embedding document %s crashed", document_id)
            await self._fail(document_id, "Unexpected error while reading the document.")

    async def _fail(self, document_id: str, message: str) -> None:
        try:
            await self._db.run(lambda c: store.set_status(c, document_id, "error", error=message))
        except Exception:
            log.exception("could not record the failure of document %s", document_id)


def _not_found() -> ApiError:
    return ApiError("document_not_found", "That document does not exist.", 404)
