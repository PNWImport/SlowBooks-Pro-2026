"""OCR route error translation, template overrides, and intake boundaries."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.bills import Bill
from app.models.contacts import Vendor
from app.routes import ocr
from app.services import ocr_engines, ocr_regions, ocr_service


class Engine:
    name = "synthetic"

    def __init__(self, result=None, error=None, reason=None):
        self.result = result
        self.error = error
        self.reason = reason

    def unavailable_reason(self):
        return self.reason

    def recognize(self, data):
        if self.error:
            raise self.error
        return self.result


def _scan_mocks(monkeypatch, engine):
    monkeypatch.setattr(ocr.ocr_engines, "get_engine", lambda setting: engine)
    monkeypatch.setattr(ocr, "get_setting_raw", lambda db, key: None)


def test_filename_and_scan_error_boundaries(client, monkeypatch):
    with pytest.raises(Exception):
        ocr._sanitize_filename("")
    with pytest.raises(Exception):
        ocr._sanitize_filename("...")
    with pytest.raises(Exception):
        ocr._sanitize_filename(" .")
    assert (
        client.post(
            "/api/ocr/receipt",
            files={"file": ("receipt.txt", b"x", "image/png")},
        ).status_code
        == 400
    )

    for error in [
        ocr_engines.EngineUnavailable("engine gone"),
        ocr_service.OCRRuntimeError("bad image"),
    ]:
        _scan_mocks(monkeypatch, Engine(error=error))
        response = client.post(
            "/api/ocr/receipt",
            files={"file": ("receipt.png", b"x", "image/png")},
        )
        assert response.status_code in (200, 400)


def test_scan_template_overrides_all_fields(client, monkeypatch):
    word = ocr_engines.WordBox("word", 1, 2, 3, 4, 99)
    result = ocr_engines.OcrResult(
        text="Merchant Name\nTotal 1.00",
        words=[word],
        engine="synthetic",
        language="eng",
    )
    _scan_mocks(monkeypatch, Engine(result=result))
    monkeypatch.setattr(ocr.ocr_service, "save_intake", lambda *args: "a" * 32)
    monkeypatch.setattr(
        ocr.ocr_service,
        "extract_receipt",
        lambda text: {
            "merchant": {"value": "Old Merchant", "confidence": "low"},
            "date": None,
            "total": "1.00",
            "total_confidence": "low",
            "subtotal": None,
            "tax": None,
            "tax_detected": False,
            "partial_reasons": ["date not found"],
        },
    )
    monkeypatch.setattr(ocr.ocr_template_store, "find_for_scan", lambda *args: object())
    monkeypatch.setattr(
        ocr.ocr_template_store,
        "apply_template",
        lambda *args, **kwargs: {
            "total": {"value": "12.00", "confidence": "high"},
            "subtotal": {"value": "10.00", "confidence": "high"},
            "tax": {"value": "2.00", "confidence": "high"},
            "date": {"value": "2026-09-08", "confidence": "high"},
            "reference": {"value": "R-1", "confidence": "high"},
            "merchant": {"value": "New Merchant", "confidence": "high"},
        },
    )
    monkeypatch.setattr(ocr.ocr_template_store, "reads_are_clean", lambda reads: True)
    response = client.post(
        "/api/ocr/receipt",
        files={"file": ("receipt.png", b"x", "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["template_applied"] is True
    assert body["merchant"]["value"] == "New Merchant"
    assert body["date"] == "2026-09-08" and body["reference"] == "R-1"


def test_bill_attachment_and_intake_image_paths(client, db_session, monkeypatch):
    vendor = Vendor(name="OCR Vendor", is_active=True)
    db_session.add(vendor)
    db_session.flush()
    bill = Bill(
        bill_number="OCR-BILL",
        vendor_id=vendor.id,
        date=date(2026, 9, 8),
        total=Decimal("1"),
        balance_due=Decimal("1"),
    )
    db_session.add(bill)
    db_session.commit()
    intake_id = ocr_service.save_intake(db_session, b"image", "receipt.png", "image/png")
    assert client.get(f"/api/ocr/intake/{intake_id}/image").content == b"image"
    attached = client.post(
        f"/api/ocr/intake/{intake_id}/attach",
        json={"entity_type": "bill", "entity_id": bill.id},
    )
    assert attached.status_code == 201, attached.text
    # The scan became the attachment: no pending copy remains.
    assert client.get(f"/api/ocr/intake/{intake_id}/image").status_code == 404

    monkeypatch.setattr(ocr.ocr_service, "get_intake", lambda db, key: None)
    assert client.get("/api/ocr/intake/missing/image").status_code == 404

    pdf = {"data": b"pdf", "mime_type": "application/pdf"}
    monkeypatch.setattr(ocr.ocr_service, "get_intake", lambda db, key: pdf)
    monkeypatch.setattr(ocr.ocr_service, "rasterize_pdf", lambda data: (b"png", 1))
    assert client.get("/api/ocr/intake/pdf/image").content == b"png"
    monkeypatch.setattr(
        ocr.ocr_service,
        "rasterize_pdf",
        lambda data: (_ for _ in ()).throw(ValueError("bad pdf")),
    )
    assert client.get("/api/ocr/intake/pdf/image").status_code == 400


@pytest.mark.parametrize(
    "error",
    [
        ocr_regions.RegionError("bad region"),
        ValueError("bad image"),
        ocr_service.OCRRuntimeError("ocr failed"),
    ],
)
def test_region_error_translation(client, monkeypatch, error):
    monkeypatch.setattr(
        ocr.ocr_service,
        "get_intake",
        lambda db, key: {"data": b"image", "mime_type": "image/png"},
    )
    _scan_mocks(monkeypatch, Engine(result=None))
    monkeypatch.setattr(
        ocr.ocr_regions,
        "ocr_region",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )
    response = client.post(
        "/api/ocr/intake/test/region",
        json={"left": 0, "top": 0, "width": 10, "height": 10},
    )
    assert response.status_code == 400


def test_region_missing_unavailable_and_template_save_isolation(client, monkeypatch):
    monkeypatch.setattr(ocr.ocr_service, "get_intake", lambda db, key: None)
    body = {"left": 0, "top": 0, "width": 10, "height": 10}
    assert client.post("/api/ocr/intake/test/region", json=body).status_code == 404
    monkeypatch.setattr(
        ocr.ocr_service,
        "get_intake",
        lambda db, key: {"data": b"image", "mime_type": "image/png"},
    )
    _scan_mocks(monkeypatch, Engine(reason="unavailable"))
    assert client.post("/api/ocr/intake/test/region", json=body).status_code == 400

    engine = Engine(error=RuntimeError("template recognition failed"))
    _scan_mocks(monkeypatch, engine)
    monkeypatch.setattr(
        ocr.ocr_regions,
        "ocr_region",
        lambda *args, **kwargs: {
            "text": "10.00",
            "value": "10.00",
            "field_type": "amount",
            "confidence": "high",
        },
    )
    response = client.post(
        "/api/ocr/intake/test/region",
        json={
            **body,
            "field_type": "amount",
            "merchant": "Merchant",
            "field_key": "total",
            "save_template": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["template_saved"] is False
