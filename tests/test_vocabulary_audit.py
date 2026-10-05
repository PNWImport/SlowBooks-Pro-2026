"""Classification guards for the live company-vocabulary audit."""

import importlib.util
from pathlib import Path

_PATH = Path(__file__).parents[1] / "scripts" / "audit" / "vocab_walk.py"
_SPEC = importlib.util.spec_from_file_location("vocab_walk", _PATH)
assert _SPEC and _SPEC.loader
vocab_walk = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vocab_walk)


def _verdict(route, text, source=None, accounts=None):
    return vocab_walk.output_verdict(
        route,
        text,
        source,
        accounts or set(),
        unchanged_from_business=True,
    )


def test_composed_report_output_is_classified_explicitly():
    assert (
        _verdict(
            "GET /api/reports/financial-statements/pdf",
            "1100 Accounts Receivable             $250.00",
            accounts={"Accounts Receivable"},
        )
        == "chart data (account name)"
    )
    assert _verdict(
        "GET /api/reports/pledges/pdf",
        "PLEDGED  INVOICED  NOT YET INVOICED  RECEIVED",
    ).startswith("pledge lifecycle")
    assert _verdict(
        "GET /api/reports/general-ledger",
        "Pledge #1001 - Vocabulary QA Customer",
    ).startswith("stored document reference")
    assert (
        _verdict(
            "GET /api/payroll/states",
            "State Individual Income Tax Rates and Brackets",
        )
        == "tax reference data"
    )


def test_document_face_does_not_hide_unrelated_document_data():
    route = "GET /api/invoices/{invoice_id}/pdf"
    assert _verdict(route, "Invoice #1002").startswith("document face")
    assert _verdict(route, "Vocabulary QA Customer") == "data or dynamic"


def test_unknown_source_text_still_fails_as_a_code_leak():
    assert (
        _verdict("GET /api/example", "Invoice processing failed", "app/x.py:10")
        == "CODE LEAK"
    )


def test_colon_delimited_api_keys_are_identifiers_not_visible_prose():
    assert vocab_walk.classify("invoice:1") == "identifier"


def test_fill_walks_each_harvested_id_for_a_single_parameter_route():
    assert vocab_walk.fill(
        "/api/invoices/{invoice_id}/pdf", {"invoices": [3, 7]}, missing=False
    ) == ["/api/invoices/3/pdf", "/api/invoices/7/pdf"]
