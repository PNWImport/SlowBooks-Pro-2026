"""OCR intake filesystem defenses that require controlled path failures."""

import json
from datetime import datetime
from decimal import InvalidOperation
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import ocr_service as ocr

INTAKE_ID = "a" * 32


def _meta(stored_name=f"{INTAKE_ID}.png"):
    return {
        "intake_id": INTAKE_ID,
        "stored_name": stored_name,
        "created_at": datetime.now().isoformat(),
        "original_filename": "scan.png",
    }


def test_decimal_parser_fallbacks_and_skip_shapes(monkeypatch):
    monkeypatch.setattr(
        ocr, "Decimal", lambda value: (_ for _ in ()).throw(InvalidOperation())
    )
    assert ocr._normalize_amount("$1.00") == "1.00"
    assert ocr._largest_amount("$1.00") is None
    monkeypatch.undo()
    assert ocr.parse_merchant("Date 01/02/2026\n123 456\nActual Merchant Name")[0] == (
        "Actual Merchant Name"
    )
    assert ocr.parse_reference("Reg Invoice No: 123\nInvoice No: no") is None


def test_save_intake_rejects_resolved_file_and_metadata_escapes(monkeypatch, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(ocr, "INTAKE_DIR", tmp_path / "intake")
    ocr.INTAKE_DIR.mkdir()
    monkeypatch.setattr(ocr, "sweep_intake", lambda: 0)
    monkeypatch.setattr(ocr, "uuid4", lambda: SimpleNamespace(hex=INTAKE_ID))

    (ocr.INTAKE_DIR / f"{INTAKE_ID}.png").symlink_to(outside / "scan.png")
    with pytest.raises(ValueError, match="escapes intake"):
        ocr.save_intake(b"x", "scan.png", "image/png")
    (ocr.INTAKE_DIR / f"{INTAKE_ID}.png").unlink()

    (ocr.INTAKE_DIR / f"{INTAKE_ID}.json").symlink_to(outside / "scan.json")
    with pytest.raises(ValueError, match="escapes intake"):
        ocr.save_intake(b"x", "scan.jpg", "image/jpeg")


def test_get_intake_path_json_and_read_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr, "INTAKE_DIR", tmp_path)
    outside = tmp_path.parent / "outside-meta.json"
    outside.write_text(json.dumps(_meta()), encoding="utf-8")
    meta_path = tmp_path / f"{INTAKE_ID}.json"
    meta_path.symlink_to(outside)
    assert ocr.get_intake(INTAKE_ID) is None
    meta_path.unlink()

    meta_path.write_text("not-json", encoding="utf-8")
    assert ocr.get_intake(INTAKE_ID) is None
    stored = tmp_path / f"{INTAKE_ID}.png"
    meta_path.write_text(json.dumps(_meta()), encoding="utf-8")
    stored.symlink_to(tmp_path.parent / "outside-image.png")
    assert ocr.get_intake(INTAKE_ID) is None
    stored.unlink()
    stored.write_bytes(b"image")

    original = Path.read_bytes

    def fail_read(path):
        if path.name == f"{INTAKE_ID}.png":
            raise OSError("read failed")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    assert ocr.get_intake(INTAKE_ID) is None


def test_delete_and_sweep_best_effort_failures(monkeypatch, tmp_path):
    missing = tmp_path / "missing"
    monkeypatch.setattr(ocr, "INTAKE_DIR", missing)
    assert ocr.sweep_intake() == 0

    monkeypatch.setattr(ocr, "INTAKE_DIR", tmp_path)
    outside = tmp_path.parent / "outside-delete"
    outside.write_bytes(b"x")
    (tmp_path / f"{INTAKE_ID}.png").symlink_to(outside)
    ocr.delete_intake(INTAKE_ID)
    assert outside.exists()

    bad = tmp_path / f"{INTAKE_ID}.json"
    bad.write_text("not-json", encoding="utf-8")
    original = Path.unlink

    def fail_unlink(path, *args, **kwargs):
        if path == bad:
            raise OSError("unlink failed")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    ocr.delete_intake(INTAKE_ID)
    assert ocr.sweep_intake() == 1
