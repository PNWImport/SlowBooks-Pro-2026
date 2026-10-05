"""A fresh duplicate copies sale lines, not the old invoice's late charges."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.invoices import Invoice, InvoiceStatus
from app.models.transactions import TransactionLine
from app.routes.invoices import lifecycle
from tests.test_invoice_posting import _create_invoice


@pytest.mark.parametrize("tax_rate", ["0", "0.10"])
def test_duplicate_after_late_fee_posts_only_copied_sale(
    authed_client, db_session, seed_accounts, seed_customer, monkeypatch, tax_rate
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
    original = _create_invoice(authed_client, seed_customer.id, tax_rate=tax_rate)
    invoice = db_session.get(Invoice, original["id"])
    invoice.status = InvoiceStatus.SENT
    invoice.due_date = date.today() - timedelta(days=30)
    db_session.commit()
    charged = authed_client.post("/api/invoices/apply-late-fees")
    assert charged.status_code == 200, charged.text
    assert charged.json()["applied"] == 1
    db_session.expire_all()
    charged_total = invoice.total
    duplicate = authed_client.post(f"/api/invoices/{invoice.id}/duplicate")
    assert duplicate.status_code == 201, duplicate.text
    copied = db_session.get(Invoice, duplicate.json()["id"])
    assert (
        copied.subtotal == sum(line.amount for line in copied.lines) == Decimal("100")
    )
    assert copied.tax_amount == Decimal("100") * Decimal(tax_rate)
    assert copied.total == copied.balance_due == copied.subtotal + copied.tax_amount
    lines = (
        db_session.query(TransactionLine)
        .filter_by(transaction_id=copied.transaction_id)
        .all()
    )
    assert (
        sum(line.debit for line in lines)
        == sum(line.credit for line in lines)
        == copied.total
    )
    db_session.expire_all()
    assert invoice.total == charged_total
