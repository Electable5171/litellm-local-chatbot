import sqlite3
import time
from pathlib import Path

import pytest

from app.db import repo
from app.db.database import Database, DatabaseError


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "data" / "chat.db")
    database.open()
    yield database
    database.close()


def _conv(conn, **kw):
    return repo.create_conversation(conn, model="qwen3.8", thinking=True, **kw)


def test_open_creates_schema_and_sets_version(db: Database):
    assert db.run_sync(lambda c: c.execute("PRAGMA user_version").fetchone()[0]) >= 1
    assert db.run_sync(lambda c: c.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    assert db.run_sync(lambda c: c.execute("PRAGMA journal_mode").fetchone()[0]) == "wal"
    # A brand-new database has nothing to back up.
    assert not (db.path.parent / "backups").exists()


def test_reopen_is_idempotent_and_takes_no_backup(tmp_path: Path):
    path = tmp_path / "chat.db"
    first = Database(path)
    first.open()
    first.close()
    second = Database(path)
    second.open()
    second.close()
    assert not (tmp_path / "backups").exists()


def test_newer_database_is_refused_and_left_alone(tmp_path: Path):
    path = tmp_path / "chat.db"
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 999")
    raw.close()
    with pytest.raises(DatabaseError, match="newer version"):
        Database(path).open()
    check = sqlite3.connect(path)
    assert check.execute("PRAGMA user_version").fetchone()[0] == 999
    check.close()


def test_backup_kept_when_upgrading_and_pruned(tmp_path: Path, monkeypatch):
    import app.db.database as dbmod

    path = tmp_path / "chat.db"
    base = Database(path)
    base.open()
    base.close()

    real = dbmod._migrations()
    extra = real + [(real[-1][0] + 1, f"{real[-1][0] + 1:04d}_x.sql", "CREATE TABLE extra (a);")]
    monkeypatch.setattr(dbmod, "_migrations", lambda: extra)
    upgraded = Database(path)
    upgraded.open()
    backups = list((tmp_path / "backups").glob("chat-*.db"))
    assert len(backups) == 1
    assert backups[0].name.endswith(f"-v{real[-1][0]}.db")
    assert upgraded.run_sync(lambda c: c.execute("SELECT count(*) FROM extra").fetchone()[0]) == 0
    upgraded.close()

    for i in range(10):  # old backups beyond the limit are removed
        (tmp_path / "backups" / f"chat-2000010{i}-000000-v1.db").write_bytes(b"")
    upgraded2 = Database(path)
    monkeypatch.setattr(
        dbmod, "_migrations", lambda: extra + [(extra[-1][0] + 1, "0099_y.sql", "SELECT 1;")]
    )
    upgraded2.open()
    upgraded2.close()
    assert len(list((tmp_path / "backups").glob("chat-*.db"))) <= dbmod.KEEP_BACKUPS


def test_failed_migration_is_rolled_back(tmp_path: Path, monkeypatch):
    import app.db.database as dbmod

    path = tmp_path / "chat.db"
    base = Database(path)
    base.open()
    base.close()
    real = dbmod._migrations()
    bad = real + [
        (real[-1][0] + 1, "9999_bad.sql", "CREATE TABLE half (a); INSERT INTO nope VALUES (1);")
    ]
    monkeypatch.setattr(dbmod, "_migrations", lambda: bad)
    with pytest.raises(DatabaseError, match="9999_bad.sql"):
        Database(path).open()
    raw = sqlite3.connect(path)
    tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "half" not in tables
    assert raw.execute("PRAGMA user_version").fetchone()[0] == real[-1][0]
    raw.close()


def test_conversation_crud(db: Database):
    conv = db.run_sync(lambda c: _conv(c, title="Hello"))
    assert conv["title"] == "Hello" and conv["thinking_enabled"] == 1
    renamed = db.run_sync(lambda c: repo.update_conversation(c, conv["id"], title="New"))
    assert renamed["title"] == "New"
    assert renamed["updated_at"] == conv["updated_at"]  # renaming does not reorder the list
    assert db.run_sync(lambda c: repo.update_conversation(c, "missing", title="x")) is None
    assert db.run_sync(lambda c: repo.delete_conversation(c, conv["id"])) is True
    assert db.run_sync(lambda c: repo.delete_conversation(c, conv["id"])) is False


def test_list_is_newest_first_and_touch_reorders(db: Database):
    a = db.run_sync(lambda c: _conv(c, title="a"))
    time.sleep(0.01)  # timestamps have millisecond resolution
    b = db.run_sync(lambda c: _conv(c, title="b"))
    assert [r["id"] for r in db.run_sync(repo.list_conversations)] == [b["id"], a["id"]]
    time.sleep(0.01)
    db.run_sync(lambda c: repo.update_conversation(c, a["id"], touch=True))
    assert [r["id"] for r in db.run_sync(repo.list_conversations)] == [a["id"], b["id"]]


def test_messages_get_increasing_positions_and_cascade_on_delete(db: Database):
    conv = db.run_sync(_conv)
    m1 = db.run_sync(lambda c: repo.add_message(c, conv["id"], "user", content="hi"))
    m2 = db.run_sync(lambda c: repo.add_message(c, conv["id"], "assistant", status="streaming"))
    assert (m1["position"], m2["position"]) == (1, 2)
    assert [m["id"] for m in db.run_sync(lambda c: repo.list_messages(c, conv["id"]))] == [
        m1["id"],
        m2["id"],
    ]
    assert db.run_sync(lambda c: repo.last_message(c, conv["id"]))["id"] == m2["id"]
    db.run_sync(lambda c: repo.delete_message(c, m2["id"]))
    m3 = db.run_sync(lambda c: repo.add_message(c, conv["id"], "assistant"))
    assert m3["position"] == 2
    db.run_sync(lambda c: repo.delete_conversation(c, conv["id"]))
    assert db.run_sync(lambda c: repo.list_messages(c, conv["id"])) == []


def test_update_message_rejects_unknown_columns(db: Database):
    conv = db.run_sync(_conv)
    m = db.run_sync(lambda c: repo.add_message(c, conv["id"], "assistant"))
    db.run_sync(lambda c: repo.update_message(c, m["id"], content="x", status="complete"))
    assert db.run_sync(lambda c: repo.get_message(c, m["id"]))["content"] == "x"
    with pytest.raises(ValueError):
        db.run_sync(lambda c: repo.update_message(c, m["id"], id="evil"))


def test_check_constraints_reject_bad_role_and_status(db: Database):
    conv = db.run_sync(_conv)
    with pytest.raises(sqlite3.IntegrityError):
        db.run_sync(lambda c: repo.add_message(c, conv["id"], "tool"))
    with pytest.raises(sqlite3.IntegrityError):
        db.run_sync(lambda c: repo.add_message(c, conv["id"], "user", status="weird"))


def test_mark_interrupted_turns_streaming_into_visible_error(db: Database):
    conv = db.run_sync(_conv)
    done = db.run_sync(lambda c: repo.add_message(c, conv["id"], "assistant", content="ok"))
    live = db.run_sync(lambda c: repo.add_message(c, conv["id"], "assistant", status="streaming"))
    assert db.run_sync(repo.mark_interrupted) == 1
    assert db.run_sync(lambda c: repo.get_message(c, live["id"]))["status"] == "error"
    assert db.run_sync(lambda c: repo.get_message(c, live["id"]))["error_code"] == "interrupted"
    assert db.run_sync(lambda c: repo.get_message(c, done["id"]))["status"] == "complete"


def test_transaction_rolls_back_on_error(db: Database):
    def work(conn):
        with repo.transaction(conn):
            _conv(conn, title="x")
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        db.run_sync(work)
    assert db.run_sync(repo.list_conversations) == []


async def test_async_run(db: Database):
    conv = await db.run(_conv)
    assert (await db.run(lambda c: repo.get_conversation(c, conv["id"])))["id"] == conv["id"]
