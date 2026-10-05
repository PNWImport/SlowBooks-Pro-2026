"""Statement selection must exclude voided or future receipts; sending is stubbed."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment
from app.routes.reports import receivables
from app.services import email_service
from app.services.settings_service import set_setting


@pytest.mark.parametrize("batch", [False, True])
def test_statement_excludes_voided_receipts(
    authed_client, db_session, seed_customer, monkeypatch, batch
):
    seed_customer.email = "synthetic@example.invalid"
    set_setting(db_session, "smtp_host", "smtp.example.invalid")
    invoice = Invoice(
        invoice_number="STATEMENT-SYN",
        customer_id=seed_customer.id,
        date=date(2020, 1, 1),
        due_date=date(2020, 1, 31),
        status=InvoiceStatus.PARTIAL,
        total=Decimal("100"),
        amount_paid=Decimal("10"),
        balance_due=Decimal("90"),
    )
    db_session.add(invoice)
    payments = [
        Payment(
            customer_id=seed_customer.id,
            date=when,
            amount=Decimal("10"),
            is_voided=void,
        )
        for when, void in [
            (date(2020, 1, 2), False),
            (date(2020, 1, 3), True),
            (date(2099, 1, 1), False),
        ]
    ]
    db_session.add_all(payments)
    db_session.commit()
    calls, emails = [], []

    def render(customer, activity, settings, as_of):
        # The voided and the future-dated receipts are not on the statement.
        assert activity["balance_due"] == Decimal("90")
        calls.append([line["amount"] for line in activity["lines"]])
        return b"synthetic-statement"

    monkeypatch.setattr(receivables, "generate_statement_pdf", render)
    monkeypatch.setattr(
        email_service, "send_email", lambda **kwargs: emails.append(kwargs) or True
    )
    if batch:
        response = authed_client.post("/api/reports/batch-email-statements")
        assert response.status_code == 200, response.text
        assert response.json() == {"sent": 1, "failed": 0, "errors": []}
        assert len(emails) == 1
    else:
        response = authed_client.get(
            f"/api/reports/customer-statement/{seed_customer.id}/pdf?as_of_date=2020-02-01"
        )
        assert response.status_code == 200, response.text
        assert response.content == b"synthetic-statement"
        assert emails == []
    assert calls == [[Decimal("100"), Decimal("-10")]]
