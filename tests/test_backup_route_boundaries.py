"""Backup HTTP boundaries using disposable files; never restore a live database."""

import pytest

from app.models.audit import AuditLog
from app.models.backups import Backup
from app.routes import backups
from app.services import backup_service


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    directory = tmp_path / "backups"
    directory.mkdir()
    monkeypatch.setattr(backup_service, "BACKUP_DIR", directory)
    return directory


@pytest.mark.parametrize(
    "result,status",
    [
        ({"success": True, "filename": "snapshot.db"}, 200),
        ({"success": False, "error": "Synthetic backup failure"}, 500),
        ({"success": False}, 500),
    ],
)
def test_create_backup_forwards_notes_and_service_result(
    client, monkeypatch, result, status
):
    calls = []

    def create(db, *, notes):
        calls.append(notes)
        return result

    monkeypatch.setattr(backups, "create_backup", create)
    response = client.post("/api/backups", json={"notes": "Synthetic snapshot"})
    assert response.status_code == status, response.text
    assert calls == ["Synthetic snapshot"]
    assert response.json() == (
        result if status == 200 else {"detail": result.get("error", "Backup failed")}
    )


@pytest.mark.parametrize(
    "kind,status",
    [
        ("valid", 200),
        ("unregistered", 404),
        ("missing", 404),
        ("external_symlink", 400),
    ],
)
def test_backup_download_requires_registered_contained_file(
    client, db_session, backup_dir, kind, status
):
    name = "snapshot.db"
    path = backup_dir / name
    if kind == "external_symlink":
        outside = backup_dir.parent / "private.db"
        outside.write_bytes(b"private outside contents")
        path.symlink_to(outside)
    elif kind != "missing":
        path.write_bytes(b"synthetic backup contents")
    if kind != "unregistered":
        db_session.add(Backup(filename=name))
        db_session.commit()
    response = client.get(f"/api/backups/download/{name}")
    assert response.status_code == status, response.text
    if status == 200:
        assert response.content == b"synthetic backup contents"
        assert response.headers["content-type"] == "application/octet-stream"
        assert name in response.headers["content-disposition"]
    else:
        assert b"private outside contents" not in response.content


def test_backup_list_omits_missing_files(client, db_session, backup_dir):
    (backup_dir / "present.db").write_bytes(b"snapshot")
    db_session.add_all(
        [Backup(filename="present.db", notes="kept"), Backup(filename="missing.db")]
    )
    db_session.commit()
    response = client.get("/api/backups")
    assert response.status_code == 200
    assert [(row["filename"], row["notes"]) for row in response.json()] == [
        ("present.db", "kept")
    ]


@pytest.mark.parametrize(
    "result,status",
    [
        ({"success": True}, 200),
        ({"success": False, "error": "Invalid filename"}, 400),
        ({"success": False, "error": "Backup not found"}, 404),
        ({"success": False}, 500),
    ],
)
def test_restore_records_intent_before_service_and_maps_result(
    client, db_session, backup_dir, monkeypatch, result, status
):
    (backup_dir / "snapshot.db").write_bytes(b"synthetic backup contents")
    calls = []

    def restore(db, filename):
        calls.append(filename)
        if filename != "snapshot.db":
            return {"success": True}  # the put-back from the safety copy
        # A service abort must not erase the already-committed intent.
        db.rollback()
        intent = (
            db.query(AuditLog).filter_by(table_name="backups", action="RESTORE").one()
        )
        assert intent.new_values == {"filename": filename}
        assert intent.source == "admin"
        return result

    safety = {"success": True, "filename": "safety.db"}
    monkeypatch.setattr(backups, "restore_backup", restore)
    monkeypatch.setattr(backups, "create_backup", lambda db, **kw: safety)
    monkeypatch.setattr(
        backup_service, "bring_restored_books_up_to_date", lambda: {"success": True}
    )
    response = client.post("/api/backups/restore", json={"filename": "snapshot.db"})
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json() == {**result, "safety_backup": "safety.db"}
    else:
        detail = response.json()["detail"]
        assert detail.startswith(result.get("error", "Restore failed"))
        if status == 500:
            # a copy that failed part-way is put back from the safety backup
            assert calls == ["snapshot.db", "safety.db"]
            assert "safety.db" in detail
    assert (
        db_session.query(AuditLog)
        .filter_by(table_name="backups", action="RESTORE")
        .count()
        == 1
    )


def test_restore_refuses_missing_and_other_company_backups_before_anything_runs(
    client, db_session, backup_dir, monkeypatch
):
    def unexpected(*args, **kwargs):
        pytest.fail("Refused restore reached the service")

    monkeypatch.setattr(backups, "restore_backup", unexpected)
    monkeypatch.setattr(backups, "create_backup", unexpected)
    r = client.post("/api/backups/restore", json={"filename": "../etc/passwd"})
    assert r.status_code == 400
    r = client.post("/api/backups/restore", json={"filename": "absent.db"})
    assert r.status_code == 404
    (backup_dir / "other-co_20260906_120000.db").write_bytes(b"x")
    r = client.post(
        "/api/backups/restore", json={"filename": "other-co_20260906_120000.db"}
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "other_company"
    assert (
        db_session.query(AuditLog)
        .filter_by(table_name="backups", action="RESTORE")
        .count()
        == 0
    )


def test_restore_external_symlink_never_reaches_service(
    client, db_session, backup_dir, monkeypatch
):
    outside = backup_dir.parent / "private.db"
    outside.write_bytes(b"preserve")
    (backup_dir / "snapshot.db").symlink_to(outside)

    def unexpected(*args, **kwargs):
        pytest.fail("Escaped backup reached restore service")

    monkeypatch.setattr(backups, "restore_backup", unexpected)
    monkeypatch.setattr(backups, "create_backup", unexpected)
    response = client.post("/api/backups/restore", json={"filename": "snapshot.db"})
    assert response.status_code == 400
    assert outside.read_bytes() == b"preserve"
    assert (
        db_session.query(AuditLog)
        .filter_by(table_name="backups", action="RESTORE")
        .count()
        == 0
    )
