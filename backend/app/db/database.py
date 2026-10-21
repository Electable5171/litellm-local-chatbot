"""SQLite storage: one file, write-ahead log, numbered SQL migrations, a backup before changes.

Python's own sqlite3 module is used (no ORM): the schema is a handful of tables, and every extra
package has to get through the company package index. SQLite calls are blocking, so the app runs
them in a worker thread through ``Database.run``; one connection and one lock keep it simple and
safe for a single user.
"""

import asyncio
import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import TypeVar

log = logging.getLogger("app.db")
T = TypeVar("T")

KEEP_BACKUPS = 5


class DatabaseError(Exception):
    """The database cannot be used; the message says what to do."""


def _migrations() -> list[tuple[int, str, str]]:
    """(version, file name, SQL) for every migration file, oldest first."""
    found = []
    for entry in resources.files("app.db.migrations").iterdir():
        name = entry.name
        if name.endswith(".sql") and name[:4].isdigit():
            found.append((int(name[:4]), name, entry.read_text(encoding="utf-8")))
    return sorted(found)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------------------------

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA secure_delete = ON")  # deleted chats are overwritten, not left behind
        self._conn = conn
        self._migrate()

    def close(self) -> None:
        # Wait for a statement that a worker thread is still running (a cancelled request leaves
        # its thread to finish); closing the connection under it is undefined.
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # -- use ---------------------------------------------------------------------------------

    def run_sync(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        if self._conn is None:
            raise DatabaseError("The database is not open.")
        with self._lock:
            return fn(self._conn)

    async def run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run ``fn(connection)`` in a worker thread without blocking the event loop."""
        return await asyncio.to_thread(self.run_sync, fn)

    # -- migrations --------------------------------------------------------------------------

    def _migrate(self) -> None:
        conn = self._conn
        assert conn is not None
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        migrations = _migrations()
        latest = migrations[-1][0] if migrations else 0
        if current > latest:
            raise DatabaseError(
                f"{self.path} was written by a newer version of this app (database version "
                f"{current}, this app understands up to {latest}). Update the app, or restore an "
                f"older copy from {self.path.parent / 'backups'}."
            )
        pending = [m for m in migrations if m[0] > current]
        if not pending:
            return
        if current > 0:
            self._backup(current)
        for version, name, sql in pending:
            log.info("applying database migration %s", name)
            try:
                conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
            except sqlite3.Error as exc:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass  # nothing was open
                raise DatabaseError(
                    f"Database migration {name} failed and was undone: {exc}. "
                    f"Your data is unchanged; a backup is in {self.path.parent / 'backups'}."
                ) from exc

    def _backup(self, version: int) -> None:
        conn = self._conn
        assert conn is not None
        folder = self.path.parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        target = folder / f"{self.path.stem}-{stamp}-v{version}.db"
        copy = sqlite3.connect(target)
        try:
            conn.backup(copy)
        finally:
            copy.close()
        log.info("backed up the database to %s before migrating", target)
        for old in sorted(folder.glob(f"{self.path.stem}-*.db"))[:-KEEP_BACKUPS]:
            old.unlink(missing_ok=True)
