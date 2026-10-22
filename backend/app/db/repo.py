"""Reading and writing conversations and messages. Every function takes an open connection."""

import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

Row = dict[str, Any]


def new_id() -> str:
    """A time-sortable id: milliseconds since 1970 in hex, then 40 random bits."""
    return f"{int(time.time() * 1000):012x}{secrets.token_hex(5)}"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _row(row: sqlite3.Row | None) -> Row | None:
    return dict(row) if row is not None else None


# -- conversations ---------------------------------------------------------------------------


def create_conversation(
    conn: sqlite3.Connection,
    *,
    model: str,
    thinking: bool,
    title: str = "",
    system_prompt: str = "",
) -> Row:
    stamp = now()
    conversation_id = new_id()
    conn.execute(
        "INSERT INTO conversations"
        " (id, title, model, thinking_enabled, system_prompt, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (conversation_id, title, model, int(thinking), system_prompt, stamp, stamp),
    )
    return get_conversation(conn, conversation_id) or {}


def get_conversation(conn: sqlite3.Connection, conversation_id: str) -> Row | None:
    return _row(
        conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    )


def list_conversations(conn: sqlite3.Connection) -> list[Row]:
    rows = conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC, id DESC").fetchall()
    return [dict(r) for r in rows]


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_conversations(
    conn: sqlite3.Connection, term: str, limit: int = 50
) -> list[tuple[Row, str | None]]:
    """Conversations whose title or message text contains ``term`` (newest first).

    Returns (conversation, text of the first matching message or None when only the title matched).
    SQLite's LIKE ignores case for plain ASCII letters only; other scripts match exactly.
    """
    pattern = _like(term)
    rows = conn.execute(
        "SELECT * FROM conversations c WHERE c.title LIKE ? ESCAPE '\\'"
        " OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id"
        "  AND m.content LIKE ? ESCAPE '\\')"
        " ORDER BY c.updated_at DESC, c.id DESC LIMIT ?",
        (pattern, pattern, limit),
    ).fetchall()
    found: list[tuple[Row, str | None]] = []
    for row in rows:
        hit = conn.execute(
            "SELECT content FROM messages WHERE conversation_id = ? AND content LIKE ? ESCAPE '\\'"
            " ORDER BY position LIMIT 1",
            (row["id"], pattern),
        ).fetchone()
        found.append((dict(row), hit[0] if hit else None))
    return found


def update_conversation(
    conn: sqlite3.Connection,
    conversation_id: str,
    *,
    title: str | None = None,
    model: str | None = None,
    thinking: bool | None = None,
    system_prompt: str | None = None,
    touch: bool = False,
    title_source: str = "user",
) -> Row | None:
    """Change settings. Renaming does not move a chat to the top of the list; ``touch`` does."""
    fields: list[tuple[str, Any]] = []
    if title is not None:
        fields.append(("title", title))
        fields.append(("title_source", title_source))
    if model is not None:
        fields.append(("model", model))
    if thinking is not None:
        fields.append(("thinking_enabled", int(thinking)))
    if system_prompt is not None:
        fields.append(("system_prompt", system_prompt))
    if touch:
        fields.append(("updated_at", now()))
    if fields:
        assignments = ", ".join(f"{name} = ?" for name, _ in fields)
        conn.execute(
            f"UPDATE conversations SET {assignments} WHERE id = ?",  # noqa: S608 (fixed column names)
            [*(value for _, value in fields), conversation_id],
        )
    return get_conversation(conn, conversation_id)


def set_generated_title(conn: sqlite3.Connection, conversation_id: str, title: str) -> bool:
    """Replace a draft title; false (nothing changed) if the user renamed the chat meanwhile."""
    cursor = conn.execute(
        "UPDATE conversations SET title = ?, title_source = 'llm'"
        " WHERE id = ? AND title_source = 'draft'",
        (title, conversation_id),
    )
    return cursor.rowcount > 0


def delete_conversation(conn: sqlite3.Connection, conversation_id: str) -> bool:
    cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return cursor.rowcount > 0


# -- messages --------------------------------------------------------------------------------


def add_message(
    conn: sqlite3.Connection,
    conversation_id: str,
    role: str,
    *,
    content: str = "",
    status: str = "complete",
) -> Row:
    position = conn.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()[0]
    message_id = new_id()
    conn.execute(
        "INSERT INTO messages (id, conversation_id, position, role, content, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (message_id, conversation_id, position, role, content, status, now()),
    )
    return get_message(conn, message_id) or {}


def get_message(conn: sqlite3.Connection, message_id: str) -> Row | None:
    return _row(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())


def list_messages(conn: sqlite3.Connection, conversation_id: str) -> list[Row]:
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY position", (conversation_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def last_message(conn: sqlite3.Connection, conversation_id: str) -> Row | None:
    return _row(
        conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY position DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
    )


MESSAGE_FIELDS = {
    "content",
    "reasoning",
    "status",
    "error_code",
    "error_message",
    "finish_reason",
    "prompt_tokens",
    "completion_tokens",
    "latency_ms",
    "ttft_ms",
    "thinking_ms",
    "trimmed",
    "sources",
}


def update_message(conn: sqlite3.Connection, message_id: str, **fields: Any) -> None:
    unknown = set(fields) - MESSAGE_FIELDS
    if unknown:
        raise ValueError(f"unknown message fields: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn.execute(
        f"UPDATE messages SET {assignments} WHERE id = ?",  # noqa: S608 (checked column names)
        [*fields.values(), message_id],
    )


def delete_message(conn: sqlite3.Connection, message_id: str) -> None:
    conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))


def delete_messages_from(conn: sqlite3.Connection, conversation_id: str, position: int) -> int:
    """Delete the message at ``position`` and every later one. Returns how many were removed."""
    cursor = conn.execute(
        "DELETE FROM messages WHERE conversation_id = ? AND position >= ?",
        (conversation_id, position),
    )
    return cursor.rowcount


def mark_interrupted(conn: sqlite3.Connection) -> int:
    """After a crash or power loss: answers left in 'streaming' become visible errors."""
    cursor = conn.execute(
        "UPDATE messages SET status = 'error', error_code = 'interrupted',"
        " error_message = 'The app stopped while this answer was being written.'"
        " WHERE status = 'streaming'"
    )
    return cursor.rowcount


def answers_since(conn: sqlite3.Connection, since: str | None) -> list[Row]:
    """The assistant messages created since an ISO UTC time (all of them when None)."""
    sql = (
        "SELECT m.id, m.conversation_id, c.title, m.status, m.prompt_tokens, m.completion_tokens,"
        " m.latency_ms, m.ttft_ms, m.thinking_ms, m.created_at"
        " FROM messages m JOIN conversations c ON c.id = m.conversation_id"
        " WHERE m.role = 'assistant'"
    )
    if since is None:
        rows = conn.execute(sql + " ORDER BY m.created_at").fetchall()
    else:
        rows = conn.execute(
            sql + " AND m.created_at >= ? ORDER BY m.created_at", (since,)
        ).fetchall()
    return [dict(r) for r in rows]
