from datetime import date
from decimal import Decimal

import pytest

from app.models.transactions import Transaction


@pytest.mark.parametrize("value", ["2026-09-07", None, "omitted"])
def test_sales_tax_payment_date(client, db_session, seed_accounts, value):
    payload = {
        "amount": "12.34",
        "pay_from_account_id": seed_accounts["1000"].id,
        "check_number": "SYNTHETIC-DATE-TEST",
    }
    if value != "omitted":
        payload["date"] = value
    response = client.post("/api/reports/sales-tax/pay", json=payload)
    assert response.status_code == 200, response.text
    txn = db_session.get(Transaction, response.json()["transaction_id"])
    assert txn.date == (
        date.fromisoformat(value) if value not in (None, "omitted") else date.today()
    )
    assert txn.source_type == "sales_tax_payment"
    assert sum(line.debit for line in txn.lines) == Decimal("12.34")
    assert sum(line.credit for line in txn.lines) == Decimal("12.34")
    assert next(
        line for line in txn.lines if line.account_id == seed_accounts["2200"].id
    ).debit == Decimal("12.34")
    assert next(
        line for line in txn.lines if line.account_id == seed_accounts["1000"].id
    ).credit == Decimal("12.34")


def test_invalid_sales_tax_date_does_not_record_payment(
    client, db_session, seed_accounts
):
    before = db_session.query(Transaction).count()
    response = client.post(
        "/api/reports/sales-tax/pay",
        json={
            "date": "2026-02-30",
            "amount": "12.34",
            "pay_from_account_id": seed_accounts["1000"].id,
        },
    )
    assert response.status_code == 422
    assert db_session.query(Transaction).count() == before
