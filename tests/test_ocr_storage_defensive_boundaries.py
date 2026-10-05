"""OCR parser fallbacks. (The intake folder's filesystem defenses went with the
folder: scans are rows of the company database now, see
test_ocr_intake_boundaries.py.)"""

from decimal import InvalidOperation

from app.services import ocr_service as ocr


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
