"""Offline collection and statement batch selection, safety and failure handling."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.contacts import Customer
from app.models.invoices import Invoice, InvoiceStatus
from app.routes.reports import receivables
from app.services import email_service
from app.services.settings_service import set_setting


def test_income_total_has_no_float_accumulation_drift(authed_client, db_session):
    for idx, amount in enumerate(["0.10", "0.20"]):
        customer = Customer(name=f"Synthetic {idx}")
        db_session.add(customer)
        db_session.flush()
        invoice(db_session, customer, f"INCOME-{idx}", 30, amount)
    db_session.commit()
    response = authed_client.get(
        "/api/reports/income-by-customer?start_date=2020-01-01&end_date=2099-01-01"
    )
    assert response.status_code == 200
    assert response.json()["total_sales"] == 0.30
    assert response.json()["total_balance"] == 0.30


def test_empty_report_defaults_and_missing_statement(authed_client):
    income = authed_client.get("/api/reports/income-by-customer")
    assert income.status_code == 200 and income.json()["items"] == []
    assert income.json()["total_sales"] == 0
    aging = authed_client.get("/api/reports/ar-aging")
    assert aging.status_code == 200 and aging.json()["totals"]["total"] == 0
    assert (
        authed_client.get("/api/reports/customer-statement/999999/pdf").status_code
        == 404
    )


def test_aging_bucket_boundaries(authed_client, db_session, seed_customer):
    for idx, days in enumerate([0, 1, 30, 31, 60, 61]):
        invoice(db_session, seed_customer, f"AGING-{idx}", days, "0.10")
    db_session.commit()
    response = authed_client.get("/api/reports/ar-aging")
    assert response.status_code == 200
    totals = response.json()["totals"]
    assert [
        totals[key] for key in ["current", "over_30", "over_60", "over_90", "total"]
    ] == [0.10, 0.20, 0.20, 0.10, 0.60]


def invoice(db, customer, number, days, amount="10", status=InvoiceStatus.SENT):
    row = Invoice(
        invoice_number=number,
        customer_id=customer.id,
        date=date.today() - timedelta(days=120),
        due_date=date.today() - timedelta(days=days),
        status=status,
        total=Decimal(amount),
        amount_paid=0,
        balance_due=Decimal(amount),
    )
    db.add(row)
    return row


@pytest.mark.parametrize("batch", [False, True])
def test_email_body_escapes_customer_and_company(
    authed_client, db_session, monkeypatch, batch
):
    customer = Customer(
        name='<img src=x onerror="bad()">', email="synthetic@example.invalid"
    )
    db_session.add(customer)
    db_session.flush()
    invoice(db_session, customer, "ESCAPE", 100)
    set_setting(db_session, "company_name", "<b>Synthetic & Company</b>")
    db_session.commit()
    sent = []
    monkeypatch.setattr(
        receivables, "generate_statement_pdf", lambda *args: b"synthetic"
    )
    monkeypatch.setattr(
        receivables, "generate_collection_letter_pdf", lambda *args: b"synthetic"
    )
    monkeypatch.setattr(
        email_service, "send_email", lambda **kwargs: sent.append(kwargs)
    )
    if batch:
        response = authed_client.post("/api/reports/batch-email-statements")
    else:
        response = authed_client.post(
            "/api/reports/collection-letters", json={"send_email": True}
        )
    assert response.status_code == 200, response.text
    assert len(sent) == 1
    assert "<img" not in sent[0]["html_body"]
    assert "&lt;img" in sent[0]["html_body"]
    if batch:
        assert "<b>" not in sent[0]["html_body"]
        assert "&lt;b&gt;Synthetic &amp; Company&lt;/b&gt;" in sent[0]["html_body"]


@pytest.mark.parametrize("letter_type,days", [("30", 30), ("60", 60), ("90", 90)])
def test_collection_cutoff_customer_filter_and_exact_total(
    authed_client, db_session, seed_customer, monkeypatch, letter_type, days
):
    other = Customer(name="Other synthetic")
    db_session.add(other)
    db_session.flush()
    chosen = [
        invoice(db_session, seed_customer, "DIME", days, "0.10"),
        invoice(db_session, seed_customer, "TWODIME", days + 1, "0.20"),
    ]
    invoice(db_session, seed_customer, "TOO-NEW", days - 1)
    invoice(db_session, seed_customer, "VOID", days, status=InvoiceStatus.VOID)
    invoice(db_session, other, "OTHER", days)
    db_session.commit()
    calls = []

    def render(customer, invoices, settings, kind, total):
        calls.append((customer.id, {row.id for row in invoices}, kind, total))
        assert all(row.days_overdue >= days for row in invoices)
        return b"synthetic"

    monkeypatch.setattr(receivables, "generate_collection_letter_pdf", render)

    def no_send(**kwargs):
        pytest.fail("Preview must not send email")

    monkeypatch.setattr(email_service, "send_email", no_send)
    response = authed_client.post(
        "/api/reports/collection-letters",
        json={
            "letter_type": letter_type,
            "customer_ids": [seed_customer.id],
            "send_email": False,
        },
    )
    assert response.status_code == 200
    assert response.json() == {"generated": 1, "emailed": 0, "errors": []}
    assert calls == [
        (seed_customer.id, {row.id for row in chosen}, letter_type, Decimal("0.30"))
    ]


@pytest.mark.parametrize("batch", [False, True])
def test_batch_continues_after_send_failure_and_missing_email(
    authed_client, db_session, monkeypatch, batch
):
    customers = [
        Customer(name=name, email=email)
        for name, email in [
            ("Fail", "fail@example.invalid"),
            ("Good", "good@example.invalid"),
            ("No email", None),
        ]
    ]
    db_session.add_all(customers)
    db_session.flush()
    for idx, customer in enumerate(customers):
        invoice(db_session, customer, f"FAILURE-{idx}", 100)
    db_session.commit()
    sent = []

    def send(**kwargs):
        if kwargs["to_email"] == "fail@example.invalid":
            raise RuntimeError("synthetic secret provider detail")
        sent.append(kwargs["to_email"])

    monkeypatch.setattr(email_service, "send_email", send)
    monkeypatch.setattr(
        receivables, "generate_statement_pdf", lambda *args: b"synthetic"
    )
    monkeypatch.setattr(
        receivables, "generate_collection_letter_pdf", lambda *args: b"synthetic"
    )
    response = (
        authed_client.post("/api/reports/batch-email-statements")
        if batch
        else authed_client.post(
            "/api/reports/collection-letters", json={"send_email": True}
        )
    )
    assert response.status_code == 200
    assert sent == ["good@example.invalid"]
    assert "synthetic secret" not in response.text
    result = response.json()
    if batch:
        assert result["sent"] == 1 and result["failed"] == 2
        assert len(result["errors"]) == 2
    else:
        assert result["generated"] == 3 and result["emailed"] == 1
        assert len(result["errors"]) == 1
