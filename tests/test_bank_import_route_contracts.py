"""Bank import upload routes decode, preview and dispatch safely."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.banking import BankAccount
from app.routes import bank_import


def _file(content=b"synthetic"):
    return {"file": ("statement.bin", content, "application/octet-stream")}


@pytest.mark.parametrize("content, expected", [(b"utf8", "utf8"), (b"\xff", "ÿ")])
def test_ofx_preview_decoding(authed_client, monkeypatch, content, expected):
    seen = []
    monkeypatch.setattr(
        bank_import,
        "parse_ofx",
        lambda text: seen.append(text)
        or [{"date": date(2026, 9, 8), "amount": Decimal("1.25")}],
    )
    response = authed_client.post("/api/bank-import/preview", files=_file(content))
    assert response.status_code == 200, response.text
    assert seen == [expected]
    assert response.json()["transactions"][0] == {
        "fitid": "",
        "date": "2026-09-08",
        "amount": 1.25,
        "payee": "",
        "memo": "",
    }


@pytest.mark.parametrize("content, expected", [(b"utf8", "utf8"), (b"\xff", "ÿ")])
def test_ofx_import_decoding(authed_client, db_session, monkeypatch, content, expected):
    account = BankAccount(name="Synthetic")
    db_session.add(account)
    db_session.commit()
    monkeypatch.setattr(bank_import, "parse_ofx", lambda text: [text])
    monkeypatch.setattr(
        bank_import,
        "import_transactions",
        lambda db, account_id, rows: {"account_id": account_id, "text": rows[0]},
    )
    response = authed_client.post(
        f"/api/bank-import/import/{account.id}", files=_file(content)
    )
    assert response.status_code == 200
    assert response.json() == {"account_id": account.id, "text": expected}


def test_bank_import_missing_accounts(authed_client):
    assert (
        authed_client.post("/api/bank-import/import/999999", files=_file()).status_code
        == 404
    )
    assert (
        authed_client.post(
            "/api/bank-import/import-csv/999999", files=_file()
        ).status_code
        == 404
    )


@pytest.mark.parametrize("content, expected", [(b"utf8", "utf8"), (b"\xff", "ÿ")])
def test_csv_import_decoding(authed_client, db_session, monkeypatch, content, expected):
    account = BankAccount(name="CSV")
    db_session.add(account)
    db_session.commit()
    monkeypatch.setattr(
        bank_import,
        "import_csv_transactions",
        lambda db, account_id, text, mapping=None: {
            "account_id": account_id,
            "text": text,
        },
    )
    response = authed_client.post(
        f"/api/bank-import/import-csv/{account.id}", files=_file(content)
    )
    assert response.status_code == 200
    assert response.json() == {"account_id": account.id, "text": expected}


def test_csv_preview_error_and_rows(authed_client, monkeypatch):
    monkeypatch.setattr(
        bank_import,
        "parse_csv",
        lambda text, mapping=None: {
            "format": "unknown",
            "error": "bad",
            "transactions": [],
        },
    )
    error = authed_client.post("/api/bank-import/preview-csv", files=_file())
    assert error.json() == {
        "format": "unknown",
        "error": "bad",
        "count": 0,
        "transactions": [],
    }
    monkeypatch.setattr(
        bank_import,
        "parse_csv",
        lambda text, mapping=None: {
            "format": "synthetic",
            "error": None,
            "transactions": [
                {
                    "date": date(2026, 9, 8),
                    "amount": Decimal("2"),
                    "fee": Decimal(".5"),
                },
                {
                    "date": "raw-date",
                    "amount": 3,
                    "payee": "P",
                    "description": "D",
                    "check_number": "7",
                    "fee": 0,
                },
            ],
        },
    )
    rows = authed_client.post("/api/bank-import/preview-csv", files=_file()).json()
    assert rows["count"] == 2
    assert rows["transactions"][0]["date"] == "2026-09-08"
    assert rows["transactions"][0]["fee"] == 0.5
    assert rows["transactions"][1]["date"] == "raw-date"
    assert rows["transactions"][1]["fee"] is None
    latin = authed_client.post("/api/bank-import/preview-csv", files=_file(b"\xff"))
    assert latin.status_code == 200
