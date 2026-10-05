"""Malformed and alternate CSV layouts for every supported bank parser."""

import csv
import io
import sys

import pytest

from app.services import bank_csv_import as bank_csv


def _reader(headers, *rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    stream.seek(0)
    return csv.DictReader(stream)


def test_detect_and_parse_dates_across_supported_and_unavailable_fallbacks(monkeypatch):
    assert bank_csv.detect_format(bank_csv.CHASE_CHECKING_SIG) == "chase_checking"
    assert bank_csv.detect_format(bank_csv.CHASE_CREDIT_SIG) == "chase_credit"
    assert bank_csv.detect_format(bank_csv.PAYPAL_SIG) == "paypal"
    assert bank_csv.detect_format(bank_csv.PAYPAL_NEW_SIG) == "paypal_new"
    assert bank_csv.detect_format(set()) == "unknown"
    assert [
        bank_csv.parse_date(value).isoformat()
        for value in ("09/08/2026", "2026-09-08", "09-08-2026", "08/09/2026")
    ] == ["2026-09-08", "2026-09-08", "2026-09-08", "2026-08-09"]
    assert bank_csv.parse_date("September 8, 2026").isoformat() == "2026-09-08"
    monkeypatch.setitem(sys.modules, "dateutil", None)
    with pytest.raises(ValueError, match="Cannot parse date"):
        bank_csv.parse_date("not-a-date")


def test_chase_parsers_skip_missing_and_invalid_rows():
    checking = bank_csv.parse_chase_checking(
        _reader(
            ["Details", "Posting Date", "Description", "Amount", "Check or Slip #"],
            {"Details": "missing", "Posting Date": "", "Amount": "1"},
            {"Details": "bad", "Posting Date": "2026-01-01", "Amount": "not-money"},
            {
                "Details": "good",
                "Posting Date": "2026-01-01",
                "Description": "Vendor",
                "Amount": "2",
                "Check or Slip #": "",
            },
        )
    )
    assert len(checking) == 1 and checking[0]["check_number"] is None

    credit = bank_csv.parse_chase_credit(
        _reader(
            ["Transaction Date", "Description", "Category", "Amount", "Memo"],
            {"Transaction Date": "", "Amount": "1"},
            {"Transaction Date": "2026-01-01", "Amount": "invalid"},
            {
                "Transaction Date": "2026-01-01",
                "Description": "Store",
                "Category": "",
                "Amount": "3",
                "Memo": "note",
            },
        )
    )
    assert credit[0]["description"] == "Store"


def test_paypal_parsers_skip_bad_and_mirror_rows_and_default_fields():
    old = bank_csv.parse_paypal(
        _reader(
            ["Date", "Name", "Type", "Status", "Gross", "Fee", "Item Title"],
            {"Date": "", "Gross": "1"},
            {"Date": "2026-01-01", "Gross": "broken"},
            {
                "Date": "2026-01-01",
                "Type": "Bank Deposit to PP Account",
                "Gross": "1",
            },
            {"Date": "2026-01-01", "Gross": "2"},
        )
    )
    assert old[0]["payee"] == "PayPal Transfer"
    assert old[0]["fee"] == 0

    new = bank_csv.parse_paypal_new(
        _reader(
            ["Date", "Name", "Description", "Gross", "Fee"],
            {"Date": "", "Gross": "1"},
            {"Date": "2026-01-01", "Gross": "bad"},
            {
                "Date": "2026-01-01",
                "Description": "Bank Deposit to PP Account x",
                "Gross": "1",
            },
            {"Date": "2026-01-01", "Name": "", "Description": "", "Gross": "3"},
        )
    )
    assert new[0]["payee"] == "PayPal Transfer"
    assert new[0]["description"] == ""
    assert new[0]["fee"] == 0


def test_parse_csv_handles_bom_empty_and_unknown_headers():
    known = bank_csv.parse_csv(
        "\ufeffDetails,Posting Date,Description,Amount,Type\nDEBIT,2026-01-01,Coffee,-1,x\n"
    )
    assert known["format"] == "chase_checking"
    assert (
        bank_csv.parse_csv("")["error"]
        == "The file is empty — there is nothing to import."
    )
    unknown = bank_csv.parse_csv("Only,Headers\n1,2\n")
    assert unknown["format"] == "unknown"
    assert "recognise this file's columns" in unknown["error"]
    assert unknown["header_row"] == ["Only", "Headers"]
