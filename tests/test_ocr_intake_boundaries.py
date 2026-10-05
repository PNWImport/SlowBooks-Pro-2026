"""Malformed intake metadata must not break receipt lookup or dashboard cleanup."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services import ocr_service as ocr


@pytest.mark.parametrize("operation", ["get", "list", "sweep"])
@pytest.mark.parametrize(
    "payload", [[], None, {"created_at": None}, {"created_at": 42}]
)
def test_malformed_metadata_fails_closed(tmp_path, monkeypatch, operation, payload):
    monkeypatch.setattr(ocr, "INTAKE_DIR", tmp_path)
    intake_id = "a" * 32
    (tmp_path / f"{intake_id}.json").write_text(json.dumps(payload))
    if operation == "get":
        assert ocr.get_intake(intake_id) is None
    elif operation == "list":
        assert ocr.list_intake() == []
    else:
        assert ocr.sweep_intake() == 1


@pytest.mark.parametrize("expired", [False, True])
def test_timezone_aware_metadata_obeys_ttl(tmp_path, monkeypatch, expired):
    monkeypatch.setattr(ocr, "INTAKE_DIR", tmp_path)
    intake_id = ocr.save_intake(b"synthetic", "receipt.png", "image/png")
    path = tmp_path / f"{intake_id}.json"
    meta = json.loads(path.read_text())
    meta["created_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=48 if expired else 1)
    ).isoformat()
    path.write_text(json.dumps(meta))
    assert len(ocr.list_intake()) == (0 if expired else 1)
    result = ocr.get_intake(intake_id)
    if expired:
        assert result is None
        assert not path.exists()
    else:
        assert result["data"] == b"synthetic"
        assert ocr.sweep_intake() == 0


@pytest.mark.parametrize("cap", ["files", "bytes"])
def test_caps_evict_oldest_receipt_first(tmp_path, monkeypatch, cap):
    monkeypatch.setattr(ocr, "INTAKE_DIR", tmp_path)
    ids = []
    for idx in range(3):
        intake_id = ocr.save_intake(b"12345", "receipt.png", "image/png")
        ids.append(intake_id)
        path = tmp_path / f"{intake_id}.json"
        meta = json.loads(path.read_text())
        meta["created_at"] = (datetime.now() - timedelta(hours=3 - idx)).isoformat()
        path.write_text(json.dumps(meta))
    monkeypatch.setattr(
        ocr,
        "INTAKE_MAX_FILES" if cap == "files" else "INTAKE_MAX_BYTES",
        2 if cap == "files" else 10,
    )
    assert ocr.sweep_intake() == 1
    assert ocr.get_intake(ids[0]) is None
    assert [ocr.get_intake(key)["data"] for key in ids[1:]] == [b"12345", b"12345"]


def test_missing_data_and_invalid_ids_are_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "INTAKE_DIR", tmp_path)
    intake_id = ocr.save_intake(b"synthetic", "../scan.unknown", "image/png")
    meta = ocr.get_intake(intake_id)
    assert meta["original_filename"] == "scan.unknown"
    assert meta["stored_name"] == intake_id + ".png"
    (tmp_path / meta["stored_name"]).unlink()
    assert ocr.get_intake(intake_id) is None
    assert ocr._intake_size(meta) == 0
    ocr.delete_intake("../bad")
    assert ocr.get_intake("../bad") is None


@pytest.mark.parametrize("operation", ["get", "list", "sweep"])
@pytest.mark.parametrize("field,value", [("intake_id", None), ("stored_name", 42)])
def test_invalid_metadata_fields_are_rejected(
    tmp_path, monkeypatch, operation, field, value
):
    monkeypatch.setattr(ocr, "INTAKE_DIR", tmp_path)
    intake_id = ocr.save_intake(b"synthetic", "receipt.png", "image/png")
    path = tmp_path / f"{intake_id}.json"
    meta = json.loads(path.read_text())
    meta[field] = value
    path.write_text(json.dumps(meta))
    if operation == "get":
        assert ocr.get_intake(intake_id) is None
    elif operation == "list":
        assert ocr.list_intake() == []
    else:
        assert ocr.sweep_intake() == 1


def test_forged_expiry_metadata_cannot_delete_another_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "INTAKE_DIR", tmp_path)
    victim = ocr.save_intake(b"keep synthetic receipt", "receipt.png", "image/png")
    forged_id = "b" * 32
    (tmp_path / f"{forged_id}.json").write_text(
        json.dumps(
            {
                "intake_id": victim,
                "stored_name": f"{victim}.png",
                "created_at": (datetime.now() - timedelta(hours=48)).isoformat(),
            }
        )
    )
    assert ocr.sweep_intake() == 1
    assert ocr.get_intake(victim)["data"] == b"keep synthetic receipt"
