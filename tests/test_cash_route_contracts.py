"""Credit-card charge, undeposited-funds, and check route contracts."""

from datetime import date
from decimal import Decimal

from app.models.accounts import Account, AccountType
from app.models.bills import Bill, BillPayment, BillPaymentAllocation
from app.models.contacts import Customer, Vendor
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentAllocation
from app.routes import checks
from app.services.accounting import create_journal_entry


def test_credit_card_charge_validation_posting_and_listing(client, seed_accounts):
    endpoint = "/api/cc-charges"
    assert (
        client.post(
            endpoint,
            json={"date": "2026-09-08", "account_id": 999999, "amount": 10},
        ).status_code
        == 404
    )
    assert (
        client.post(
            endpoint,
            json={
                "date": "2026-09-08",
                "account_id": seed_accounts["6000"].id,
                "amount": 0,
            },
        ).status_code
        == 400
    )
    created = client.post(
        endpoint,
        json={
            "date": "2026-09-08",
            "payee": "Supplier",
            "account_id": seed_accounts["6000"].id,
            "amount": 12.5,
            "memo": "Supplies",
            "reference": "CC-1",
            "function": "program",
        },
    )
    assert created.status_code == 201, created.text
    rows = client.get(endpoint).json()
    assert rows[0]["amount"] == 12.5
    assert rows[0]["account_name"] == seed_accounts["6000"].name


def test_credit_card_charge_requires_control_account(client, db_session):
    expense = Account(name="Expense", account_type=AccountType.EXPENSE)
    db_session.add(expense)
    db_session.commit()
    response = client.post(
        "/api/cc-charges",
        json={"date": "2026-09-08", "account_id": expense.id, "amount": 10},
    )
    assert response.status_code == 409
    assert "2100" in response.json()["detail"]
    assert client.get("/api/cc-charges").json() == []


def test_pending_deposit_partial_allocation_and_completion(
    client, db_session, seed_accounts
):
    undeposited = seed_accounts["1200"]
    income = seed_accounts["4000"]
    create_journal_entry(
        db_session,
        date(2026, 9, 8),
        "Customer payment",
        [
            {"account_id": undeposited.id, "debit": Decimal("30"), "credit": 0},
            {"account_id": income.id, "debit": 0, "credit": Decimal("30")},
        ],
        source_type="payment",
        reference="PAY-1",
    )
    create_journal_entry(
        db_session,
        date(2026, 9, 10),
        "Second customer payment",
        [
            {"account_id": undeposited.id, "debit": Decimal("10"), "credit": 0},
            {"account_id": income.id, "debit": 0, "credit": Decimal("10")},
        ],
        source_type="payment",
        reference="PAY-2",
    )
    db_session.commit()
    assert sum(r["amount"] for r in client.get("/api/deposits/pending").json()) == 40

    body = {
        "deposit_to_account_id": seed_accounts["1000"].id,
        "date": "2026-09-09",
        "reference": "DEP-1",
    }
    # A deposit names the payments it takes (newest first on the list); the
    # total is only a cross-check against them.
    ten, thirty = client.get("/api/deposits/pending").json()
    assert (ten["amount"], thirty["amount"]) == (10, 30)
    wrong_total = client.post(
        "/api/deposits",
        json={**body, "line_ids": [ten["transaction_line_id"]], "total": 40.01},
    )
    assert wrong_total.status_code == 400, wrong_total.text
    assert "add up to $10.00" in wrong_total.text
    unknown = client.post("/api/deposits", json={**body, "line_ids": [999999]})
    assert unknown.status_code == 400
    taken = client.post(
        "/api/deposits",
        json={**body, "line_ids": [ten["transaction_line_id"]], "total": 10},
    )
    assert taken.status_code == 200 and taken.json()["items"] == 1
    pending = client.get("/api/deposits/pending").json()
    assert len(pending) == 1
    assert pending[0]["amount"] == 30
    # The same payment cannot be deposited twice.
    again = client.post(
        "/api/deposits", json={**body, "line_ids": [ten["transaction_line_id"]]}
    )
    assert again.status_code == 400
    assert (
        client.post(
            "/api/deposits",
            json={**body, "line_ids": [thirty["transaction_line_id"]], "total": 30},
        ).status_code
        == 200
    )
    assert client.get("/api/deposits/pending").json() == []

    assert (
        client.post(
            "/api/deposits",
            json={**body, "total": 10, "deposit_to_account_id": 999999},
        ).status_code
        == 404
    )
    assert client.post("/api/deposits", json={**body, "total": 0}).status_code == 400
    # The amount-only form (no line_ids) is still accepted, but only up to
    # the money actually waiting in Undeposited Funds — both payments are
    # deposited by now, so a further $5 would overdraw it.
    overdraw = client.post("/api/deposits", json={**body, "total": 5})
    assert overdraw.status_code == 400
    assert "exceeds pending Undeposited Funds" in overdraw.json()["detail"]


def test_deposit_requires_undeposited_funds_account(client, db_session):
    bank = Account(name="Bank", account_type=AccountType.ASSET)
    db_session.add(bank)
    db_session.commit()
    pending = client.get("/api/deposits/pending")
    # With no Undeposited Funds nothing was ever received into it: the list
    # is empty, and only making a deposit is refused.
    assert pending.status_code == 200 and pending.json() == []
    response = client.post(
        "/api/deposits",
        json={"deposit_to_account_id": bank.id, "date": "2026-09-08", "total": 1},
    )
    assert response.status_code == 409
    assert "1200" in response.json()["detail"]


def test_check_printing_for_customer_and_vendor_payments(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(
        checks, "generate_check_pdf", lambda data, company: b"%PDF-test"
    )
    customer = Customer(name="Check Customer", is_active=True)
    vendor = Vendor(name="Check Vendor", is_active=True)
    db_session.add_all([customer, vendor])
    db_session.flush()
    payment = Payment(
        customer_id=customer.id,
        date=date(2026, 9, 8),
        amount=Decimal("10"),
        check_number="101",
        notes="Refund",
    )
    bill_payment = BillPayment(
        vendor_id=vendor.id,
        date=date(2026, 9, 8),
        amount=Decimal("20"),
        check_number="102",
    )
    invoice = Invoice(
        invoice_number="CHECK-INV",
        customer_id=customer.id,
        date=date(2026, 9, 8),
        status=InvoiceStatus.PAID,
        total=Decimal("10"),
        amount_paid=Decimal("10"),
        balance_due=Decimal("0"),
    )
    bill = Bill(
        bill_number="CHECK-BILL",
        vendor_id=vendor.id,
        date=date(2026, 9, 8),
        total=Decimal("20"),
        amount_paid=Decimal("20"),
        balance_due=Decimal("0"),
    )
    db_session.add_all([payment, bill_payment, invoice, bill])
    db_session.flush()
    db_session.add_all(
        [
            PaymentAllocation(
                payment_id=payment.id, invoice_id=invoice.id, amount=Decimal("10")
            ),
            BillPaymentAllocation(
                bill_payment_id=bill_payment.id,
                bill_id=bill.id,
                amount=Decimal("20"),
            ),
        ]
    )
    db_session.commit()

    assert client.get("/api/checks/print").status_code == 400
    assert client.get("/api/checks/print?payment_id=999999").status_code == 404
    assert client.get("/api/checks/print?bill_payment_id=999999").status_code == 404
    customer_pdf = client.get(f"/api/checks/print?payment_id={payment.id}")
    # A payment received is money in: the customer wrote that check.
    assert customer_pdf.status_code == 400
    assert "no check to print" in customer_pdf.json()["detail"]
    vendor_pdf = client.get(f"/api/checks/print?bill_payment_id={bill_payment.id}")
    assert vendor_pdf.status_code == 200
    assert vendor_pdf.content == b"%PDF-test"
