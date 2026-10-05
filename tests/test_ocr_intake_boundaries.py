"""Intake lifetime and caps on the company-database store (stored_files).

Pending receipt scans are rows of kind receipt_scan, not files in a shared
folder; the filesystem-metadata cases (malformed sidecar JSON, forged
metadata, symlink escapes) no longer exist as inputs.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.stored_files import KIND_ATTACHMENT, StoredFile
from app.services import ocr_service as ocr


def _row(db, intake_id):
    db.expire_all()
    return db.query(StoredFile).filter(StoredFile.token == intake_id).first()


def _age(db, intake_id, hours):
    row = _row(db, intake_id)
    row.created_at = datetime.now(timezone.utc) - timedelta(hours=hours)
    db.commit()


@pytest.mark.parametrize("expired", [False, True])
def test_timezone_aware_rows_obey_ttl(db_session, expired):
    intake_id = ocr.save_intake(db_session, b"synthetic", "receipt.png", "image/png")
    _age(db_session, intake_id, 48 if expired else 1)
    assert len(ocr.list_intake(db_session)) == (0 if expired else 1)
    result = ocr.get_intake(db_session, intake_id)
    if expired:
        assert result is None
        assert _row(db_session, intake_id) is None
    else:
        assert result["data"] == b"synthetic"
        assert ocr.sweep_intake(db_session) == 0


def test_naive_created_at_is_read_as_utc(db_session):
    intake_id = ocr.save_intake(db_session, b"synthetic", "receipt.png", "image/png")
    row = _row(db_session, intake_id)
    row.created_at = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(
        tzinfo=None
    )
    db_session.commit()
    assert len(ocr.list_intake(db_session)) == 1
    assert ocr.get_intake(db_session, intake_id)["data"] == b"synthetic"


def test_expired_rows_are_swept(db_session):
    intake_id = ocr.save_intake(db_session, b"synthetic", "receipt.png", "image/png")
    _age(db_session, intake_id, 48)
    assert ocr.sweep_intake(db_session) == 1
    db_session.commit()
    assert _row(db_session, intake_id) is None


@pytest.mark.parametrize("cap", ["files", "bytes"])
def test_caps_evict_oldest_receipt_first(db_session, monkeypatch, cap):
    ids = []
    for idx in range(3):
        intake_id = ocr.save_intake(db_session, b"12345", "receipt.png", "image/png")
        ids.append(intake_id)
        _age(db_session, intake_id, 3 - idx)
    monkeypatch.setattr(
        ocr,
        "INTAKE_MAX_FILES" if cap == "files" else "INTAKE_MAX_BYTES",
        2 if cap == "files" else 10,
    )
    assert ocr.sweep_intake(db_session) == 1
    db_session.commit()
    assert ocr.get_intake(db_session, ids[0]) is None
    assert [ocr.get_intake(db_session, key)["data"] for key in ids[1:]] == [
        b"12345",
        b"12345",
    ]


def test_filename_is_reduced_and_invalid_ids_are_safe(db_session):
    intake_id = ocr.save_intake(db_session, b"synthetic", "../scan.unknown", "image/png")
    meta = ocr.get_intake(db_session, intake_id)
    assert meta["original_filename"] == "scan.unknown"
    assert meta["size"] == len(b"synthetic")
    ocr.delete_intake(db_session, "../bad")
    assert ocr.get_intake(db_session, "../bad") is None
    assert ocr.get_intake(db_session, None) is None
    ocr.delete_intake(db_session, intake_id)
    assert ocr.get_intake(db_session, intake_id) is None


def test_missing_bytes_fail_closed(db_session):
    intake_id = ocr.save_intake(db_session, b"synthetic", "receipt.png", "image/png")
    row = _row(db_session, intake_id)
    row.missing = True
    db_session.commit()
    assert ocr.get_intake(db_session, intake_id) is None


def test_attached_receipt_is_no_longer_pending(db_session):
    intake_id = ocr.save_intake(db_session, b"synthetic", "receipt.png", "image/png")
    row = _row(db_session, intake_id)
    row.kind = KIND_ATTACHMENT
    row.token = None
    db_session.commit()
    assert ocr.list_intake(db_session) == []
    assert ocr.get_intake(db_session, intake_id) is None
    # Sweeping never touches a file that is now an attachment.
    _age_row = db_session.get(StoredFile, row.id)
    _age_row.created_at = datetime.now(timezone.utc) - timedelta(hours=96)
    db_session.commit()
    assert ocr.sweep_intake(db_session) == 0
    assert db_session.get(StoredFile, row.id) is not None
