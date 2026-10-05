"""Late fees affect only eligible sent balances and post balanced entries once."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.invoices import Invoice, InvoiceStatus
from app.models.transactions import Transaction, TransactionLine
from app.routes.invoices import lifecycle
from tests.test_invoice_posting import _create_invoice
from tests.test_jobs import _job


@pytest.mark.parametrize(
    "status, age, balance, applied, eligible",
    [
        (InvoiceStatus.SENT, 15, "100", 1, 1),
        (InvoiceStatus.PARTIAL, 16, "40", 1, 1),
        (InvoiceStatus.DRAFT, 30, "100", 0, 0),
        (InvoiceStatus.VOID, 30, "100", 0, 0),
        (InvoiceStatus.PAID, 30, "0", 0, 0),
        (InvoiceStatus.SENT, 14, "100", 0, 0),
        (InvoiceStatus.SENT, 30, "0.01", 0, 1),
    ],
)
def test_late_fee_eligibility_and_repeat_safety(
    authed_client,
    db_session,
    seed_accounts,
    seed_customer,
    monkeypatch,
    status,
    age,
    balance,
    applied,
    eligible,
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
    job = _job(authed_client, seed_customer.id, "Late-fee project")
    invoice.job_id = job["id"]
    invoice.status = status
    invoice.due_date = date.today() - timedelta(days=age)
    invoice.balance_due = Decimal(balance)
    db_session.commit()
    response = authed_client.post("/api/invoices/apply-late-fees")
    assert response.status_code == 200, response.text
    assert response.json() == {"applied": applied, "total_overdue": eligible}
    db_session.expire_all()
    invoice = db_session.get(Invoice, created["id"])
    fee = (
        (Decimal(balance) * Decimal("0.015")).quantize(Decimal("0.01"))
        if applied
        else Decimal("0")
    )
    assert invoice.balance_due == Decimal(balance) + fee
    assert invoice.total == Decimal("100") + fee
    assert invoice.subtotal + invoice.tax_amount == invoice.total
    entries = (
        db_session.query(Transaction)
        .filter_by(source_type="late_fee", source_id=invoice.id)
        .all()
    )
    assert len(entries) == applied
    if entries:
        assert entries[0].job_id == job["id"]
        lines = (
            db_session.query(TransactionLine)
            .filter_by(transaction_id=entries[0].id)
            .all()
        )
        assert (
            sum(row.debit for row in lines) == sum(row.credit for row in lines) == fee
        )
        assert all(row.job_id == job["id"] for row in lines)
    repeated = authed_client.post("/api/invoices/apply-late-fees")
    assert repeated.status_code == 200
    assert repeated.json()["applied"] == 0


@pytest.mark.parametrize("enabled", [False, True])
def test_late_fee_configuration_rejection(authed_client, monkeypatch, enabled):
    monkeypatch.setattr(
        lifecycle, "get_settings", lambda db: {"late_fee_enabled": str(enabled).lower()}
    )
    response = authed_client.post("/api/invoices/apply-late-fees")
    assert response.status_code == 400
    assert ("Receivable" if enabled else "not enabled") in response.json()["detail"]
