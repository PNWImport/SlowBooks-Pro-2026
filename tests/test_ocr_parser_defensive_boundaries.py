"""Small defensive OCR parser/probe branches requiring no native binaries."""

import subprocess

from app.services import ocr_service as ocr


def test_probe_tolerates_version_and_language_failures(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_cmd", lambda: "tesseract")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing")),
    )
    info = ocr._probe_tesseract()
    assert info["available"] is True
    assert info["version"] is None and info["languages"] == []


def test_parser_rejection_boundaries(monkeypatch):
    monkeypatch.setattr(
        ocr, "tesseract_info", lambda: {"languages": [], "poppler": False}
    )
    assert ocr.poppler_available() is False
    assert ocr.ocr_language() is None
    assert ocr._numeric_date("Receipt 1/2/123") is None
    assert ocr._is_positive("not-a-number") is False
    assert ocr._smallest(["not-a-number"]) == "not-a-number"
    merchant, confidence = ocr.parse_merchant(
        "01/02/2026\n(206) 555-1212\n12345\nActual Merchant Name"
    )
    assert (merchant, confidence) == ("Actual Merchant Name", "low")
    assert ocr.parse_reference("Reg No: 123\nInvoice No: 456") == "456"
    assert ocr.parse_reference("Receipt 01/02/2026") is None


def test_extract_receipt_survives_invalid_decimal_components(monkeypatch):
    monkeypatch.setattr(ocr, "parse_merchant", lambda text: ("Merchant Name", "high"))
    monkeypatch.setattr(ocr, "parse_total", lambda text: ("bad", "high"))
    monkeypatch.setattr(ocr, "parse_tax", lambda text: ("also-bad", "bad"))
    result = ocr.extract_receipt("text")
    assert result["total"] == "bad"
