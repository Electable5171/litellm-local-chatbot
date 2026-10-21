"""Documents and chunks. Every function takes an open connection."""

import sqlite3

from app.db.repo import Row, new_id, now

DOCUMENT_COLUMNS = (
    "id, filename, sha256, mime, size_bytes, status, error, page_count, chunk_count,"
    " embedding_model, embedding_dim, created_at"
)


def _row(row: sqlite3.Row | None) -> Row | None:
    return dict(row) if row is not None else None


def get_document(conn: sqlite3.Connection, document_id: str) -> Row | None:
    return _row(
        conn.execute(
            f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE id = ?",  # noqa: S608 (constant)
            (document_id,),
        ).fetchone()
    )


def get_by_sha256(conn: sqlite3.Connection, sha256: str) -> Row | None:
    return _row(
        conn.execute(
            f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE sha256 = ?",  # noqa: S608 (constant)
            (sha256,),
        ).fetchone()
    )


def list_documents(conn: sqlite3.Connection) -> list[Row]:
    """Newest first, each with how many chunks already have an embedding (the progress)."""
    rows = conn.execute(
        f"SELECT {DOCUMENT_COLUMNS},"  # noqa: S608 (constant)
        " (SELECT COUNT(*) FROM chunks c WHERE c.document_id = documents.id"
        "  AND c.embedding IS NOT NULL) AS embedded_count"
        " FROM documents ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def create_document(
    conn: sqlite3.Connection,
    *,
    filename: str,
    sha256: str,
    mime: str,
    size_bytes: int,
    page_count: int | None,
    chunks: list[tuple[int, int | None, str, int]],
) -> Row:
    """Store a document with its chunks (ordinal, page, text, token_count), not yet embedded."""
    document_id = new_id()
    conn.execute(
        "INSERT INTO documents"
        " (id, filename, sha256, mime, size_bytes, status, page_count, chunk_count, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'processing', ?, ?, ?)",
        (document_id, filename, sha256, mime, size_bytes, page_count, len(chunks), now()),
    )
    conn.executemany(
        "INSERT INTO chunks (id, document_id, ordinal, page, text, token_count)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [(new_id(), document_id, o, page, text, tokens) for o, page, text, tokens in chunks],
    )
    return get_document(conn, document_id) or {}


def pending_chunks(conn: sqlite3.Connection, document_id: str, limit: int) -> list[Row]:
    rows = conn.execute(
        "SELECT id, text FROM chunks WHERE document_id = ? AND embedding IS NULL"
        " ORDER BY ordinal LIMIT ?",
        (document_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def save_embeddings(conn: sqlite3.Connection, vectors: list[tuple[bytes, str]]) -> None:
    """(packed vector, chunk id) pairs."""
    conn.executemany("UPDATE chunks SET embedding = ? WHERE id = ?", vectors)


def set_status(
    conn: sqlite3.Connection,
    document_id: str,
    status: str,
    *,
    error: str | None = None,
    embedding_model: str | None = None,
    embedding_dim: int | None = None,
) -> None:
    conn.execute(
        "UPDATE documents SET status = ?, error = ?,"
        " embedding_model = COALESCE(?, embedding_model),"
        " embedding_dim = COALESCE(?, embedding_dim) WHERE id = ?",
        (status, error, embedding_model, embedding_dim, document_id),
    )


def processing_ids(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT id FROM documents WHERE status = 'processing'")]


def delete_document(conn: sqlite3.Connection, document_id: str) -> bool:
    return conn.execute("DELETE FROM documents WHERE id = ?", (document_id,)).rowcount > 0


# -- attachments ---------------------------------------------------------------------------------


def attach(conn: sqlite3.Connection, conversation_id: str, document_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO conversation_documents (conversation_id, document_id, created_at)"
        " VALUES (?, ?, ?)",
        (conversation_id, document_id, now()),
    )


def detach(conn: sqlite3.Connection, conversation_id: str, document_id: str) -> bool:
    cursor = conn.execute(
        "DELETE FROM conversation_documents WHERE conversation_id = ? AND document_id = ?",
        (conversation_id, document_id),
    )
    return cursor.rowcount > 0


def attached_documents(conn: sqlite3.Connection, conversation_id: str) -> list[Row]:
    rows = conn.execute(
        "SELECT d.id, d.filename, d.status, d.error, d.page_count, d.chunk_count,"
        " d.embedding_model, d.embedding_dim, d.size_bytes, d.mime, d.created_at,"
        " (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id"
        "  AND c.embedding IS NOT NULL) AS embedded_count"
        " FROM conversation_documents cd JOIN documents d ON d.id = cd.document_id"
        " WHERE cd.conversation_id = ? ORDER BY cd.created_at, d.id",
        (conversation_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def chunks_of(conn: sqlite3.Connection, document_ids: list[str]) -> list[Row]:
    """All chunks of the given documents, in document and reading order."""
    if not document_ids:
        return []
    marks = ",".join("?" * len(document_ids))
    rows = conn.execute(
        "SELECT c.id, c.document_id, c.ordinal, c.page, c.text, c.token_count, c.embedding"  # noqa: S608
        f" FROM chunks c WHERE c.document_id IN ({marks}) AND c.embedding IS NOT NULL"
        " ORDER BY c.document_id, c.ordinal",
        document_ids,
    ).fetchall()
    return [dict(r) for r in rows]
