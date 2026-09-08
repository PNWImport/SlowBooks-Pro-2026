"""Backup tools must use the application's credentials and transport policy."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import backup_service


@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_backup_tools_preserve_url_credentials_and_tls(
    operation, monkeypatch, tmp_path, db_session
):
    monkeypatch.setattr(
        backup_service,
        "DATABASE_URL",
        "postgresql://book%40keeper:p%40ss%3Aword@db.example/books"
        "?sslmode=verify-full&sslrootcert=%2Fcerts%2Froot.pem",
    )
    monkeypatch.setattr(backup_service, "BACKUP_DIR", tmp_path)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "pg_dump":
            Path(args[args.index("-f") + 1]).write_bytes(b"test dump")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(backup_service.subprocess, "run", run)
    if operation == "backup":
        result = backup_service.create_backup(db_session)
    else:
        (tmp_path / "snapshot.dump").write_bytes(b"test dump")
        result = backup_service.restore_backup(db_session, "snapshot.dump")
    assert result["success"]
    args, kwargs = calls[0]
    assert args[args.index("-U") + 1] == "book@keeper"
    assert kwargs["env"]["PGPASSWORD"] == "p@ss:word"
    assert kwargs["env"]["PGSSLMODE"] == "verify-full"
    assert kwargs["env"]["PGSSLROOTCERT"] == "/certs/root.pem"
    assert "p@ss:word" not in " ".join(args)
    if operation == "restore":
        assert "--single-transaction" in args


def test_restore_nonzero_exit_is_failure_even_without_english_error(
    monkeypatch, tmp_path, db_session
):
    monkeypatch.setattr(backup_service, "DATABASE_URL", "postgresql://u:p@host/db")
    monkeypatch.setattr(backup_service, "BACKUP_DIR", tmp_path)
    (tmp_path / "snapshot.dump").write_bytes(b"test dump")
    monkeypatch.setattr(
        backup_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="failed"),
    )
    assert not backup_service.restore_backup(db_session, "snapshot.dump")["success"]
