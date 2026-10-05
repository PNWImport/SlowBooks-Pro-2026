"""Voiding an invoice must reverse its separately posted late fees too."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.invoices import Invoice, InvoiceStatus
from app.models.transactions import Transaction, TransactionLine
from app.routes.invoices import lifecycle
from tests.test_invoice_posting import _create_invoice


@pytest.mark.parametrize("block_fee_date", [False, True])
def test_void_cancels_invoice_and_late_fee_ledger(
    authed_client, db_session, seed_accounts, seed_customer, monkeypatch, block_fee_date
):
    monkeypatch.setattr(
        lifecycle,
        "get_settings",
        lambda db: {
            "late_fee_enabled": "true",
            "late_fee_rate": "1.5",
            "late_fee_grace_days": "15",
        },
    )
    created = _create_invoice(authed_client, seed_customer.id)
    invoice = db_session.get(Invoice, created["id"])
    invoice.status = InvoiceStatus.SENT
    invoice.due_date = date.today() - timedelta(days=30)
    db_session.commit()
    fees = authed_client.post("/api/invoices/apply-late-fees")
    assert fees.status_code == 200, fees.text
    assert fees.json()["applied"] == 1
    if block_fee_date:

        def reject_fee_date(db, posting_date):
            if posting_date == date.today():
                raise HTTPException(status_code=400, detail="Synthetic closed fee date")

        monkeypatch.setattr(lifecycle, "check_closing_date", reject_fee_date)
    response = authed_client.post(f"/api/invoices/{invoice.id}/void")
    if block_fee_date:
        assert response.status_code == 400
        db_session.expire_all()
        assert db_session.get(Invoice, invoice.id).status == InvoiceStatus.SENT
        assert (
            db_session.query(Transaction)
            .filter_by(source_type="invoice_void", source_id=invoice.id)
            .count()
            == 0
        )
        return
    assert response.status_code == 200, response.text
    entries = (
        db_session.query(Transaction)
        .filter(
            Transaction.source_id == invoice.id,
            Transaction.source_type.in_(["invoice", "late_fee", "invoice_void"]),
        )
        .all()
    )
    lines = (
        db_session.query(TransactionLine)
        .filter(TransactionLine.transaction_id.in_([entry.id for entry in entries]))
        .all()
    )
    balances = defaultdict(Decimal)
    for line in lines:
        balances[line.account_id] += line.debit - line.credit
    assert all(value == 0 for value in balances.values()), dict(balances)
    reversal_dates = sorted(
        entry.date for entry in entries if entry.source_type == "invoice_void"
    )
    assert reversal_dates == sorted([date(2026, 4, 1), date.today()])
    assert authed_client.post(f"/api/invoices/{invoice.id}/void").status_code == 400
    assert (
        db_session.query(Transaction)
        .filter_by(source_type="invoice_void", source_id=invoice.id)
        .count()
        == 2
    )
