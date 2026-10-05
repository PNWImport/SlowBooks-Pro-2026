"""Exercise backup failures using temporary files and mocked external tools."""

import sqlite3
import subprocess
from contextlib import closing
from types import SimpleNamespace

import pytest

from app.models.backups import Backup
from app.services import backup_service as service


@pytest.mark.parametrize(
    "filename", ["", "a" * 256 + ".db", ".hidden.db", "snapshot..db", "snapshot.txt"]
)
def test_invalid_backup_names_are_rejected(filename, monkeypatch, db_session):
    def unexpected_restore(*args, **kwargs):
        pytest.fail("Invalid filename reached the restore operation")

    monkeypatch.setattr(service, "_restore_sqlite_backup", unexpected_restore)
    assert service.restore_backup(db_session, filename) == {
        "success": False,
        "error": "Invalid filename",
    }


@pytest.mark.parametrize("operation", ["backup", "restore"])
@pytest.mark.parametrize("failure", ["exit", "timeout", "missing"])
def test_postgres_failures_are_safe_and_do_not_record_success(
    operation, failure, monkeypatch, tmp_path, db_session
):
    monkeypatch.setattr(service, "DATABASE_URL", "postgresql://test@host/books")
    monkeypatch.setattr(service, "BACKUP_DIR", tmp_path)
    snapshot = tmp_path / "snapshot.dump"
    snapshot.write_bytes(b"existing backup")

    def fail(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("tool", 300)
        if failure == "missing":
            raise FileNotFoundError("private installation path")
        return SimpleNamespace(returncode=1, stderr="private connection detail")

    monkeypatch.setattr(service.subprocess, "run", fail)
    before = db_session.query(Backup).count()
    result = (
        service.create_backup(db_session)
        if operation == "backup"
        else service.restore_backup(db_session, snapshot.name)
    )
    assert result["success"] is False
    assert "private" not in result["error"]
    assert db_session.query(Backup).count() == before
    assert snapshot.read_bytes() == b"existing backup"


def test_sqlite_failed_snapshot_removes_partial_file(monkeypatch, tmp_path, db_session):
    live = tmp_path / "live.db"
    live.write_bytes(b"source")
    backups = tmp_path / "backups"
    backups.mkdir()
    monkeypatch.setattr(service, "DATABASE_URL", f"sqlite:///{live}")
    monkeypatch.setattr(service, "BACKUP_DIR", backups)

    class Connection:
        def backup(self, destination):
            raise sqlite3.DatabaseError("private source path")

        def close(self):
            pass

    def connect(path):
        if path != live:
            path.write_bytes(b"partial")
        return Connection()

    monkeypatch.setattr(service.sqlite3, "connect", connect)
    assert service.create_backup(db_session) == {
        "success": False,
        "error": "SQLite backup failed. Check logs.",
    }
    assert list(backups.iterdir()) == []
    assert live.read_bytes() == b"source"


def test_corrupt_sqlite_restore_preserves_live_data(monkeypatch, tmp_path, db_session):
    live = tmp_path / "live.db"
    with closing(sqlite3.connect(live)) as connection, connection:
        connection.execute("CREATE TABLE proof (value TEXT)")
        connection.execute("INSERT INTO proof VALUES ('preserved')")
    snapshot = tmp_path / "broken.db"
    snapshot.write_bytes(b"not a database")
    monkeypatch.setattr(service, "DATABASE_URL", f"sqlite:///{live}")
    monkeypatch.setattr(service, "BACKUP_DIR", tmp_path)
    assert service.restore_backup(db_session, snapshot.name) == {
        "success": False,
        "error": "SQLite restore failed. Check logs.",
    }
    with closing(sqlite3.connect(live)) as connection:
        assert connection.execute("SELECT value FROM proof").fetchone() == (
            "preserved",
        )


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///", "sqlite:///:memory:"])
def test_restore_requires_file_backed_database(url, monkeypatch, tmp_path, db_session):
    monkeypatch.setattr(service, "DATABASE_URL", url)
    monkeypatch.setattr(service, "BACKUP_DIR", tmp_path)
    (tmp_path / "snapshot.db").write_bytes(b"placeholder")
    result = service.restore_backup(db_session, "snapshot.db")
    assert result["success"] is False
    assert "file-backed" in result["error"]
