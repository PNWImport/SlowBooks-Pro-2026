"""Provider-neutral checkout, webhook, polling, and payment-link branches."""

from datetime import date
from decimal import Decimal

from app.models.contacts import Customer
from app.models.invoices import Invoice, InvoiceStatus
from app.routes import provider_payments
from app.services.payments.base import CheckoutSession, PaymentResult


class FakeProvider:
    name = "stripe"
    display_name = "Fake Stripe"
    settings_keys = ()

    def __init__(self, *, enabled=True, configured=True, webhook=None, poll=None):
        self.enabled = enabled
        self.configured = configured
        self.webhook = webhook
        self.poll = poll or PaymentResult(status="pending", external_id="checkout-1")

    def is_enabled(self, settings):
        return self.enabled

    def is_configured(self, settings):
        return self.configured

    def create_checkout(self, invoice, settings, base_url):
        return CheckoutSession(
            url="https://checkout.example/session", external_id="checkout-1"
        )

    def verify_webhook(self, payload, headers, settings):
        if isinstance(self.webhook, Exception):
            raise self.webhook
        return self.webhook

    def poll_status(self, external_id, settings):
        return self.poll


def _invoice(db_session, *, number, token, status=InvoiceStatus.SENT, balance="10"):
    customer = db_session.query(Customer).first()
    if customer is None:
        customer = Customer(name="Provider Customer", is_active=True)
        db_session.add(customer)
        db_session.flush()
    invoice = Invoice(
        invoice_number=number,
        customer_id=customer.id,
        date=date(2026, 9, 8),
        status=status,
        subtotal=Decimal("10"),
        tax_rate=Decimal("0"),
        tax_amount=Decimal("0"),
        total=Decimal("10"),
        amount_paid=Decimal("0"),
        balance_due=Decimal(balance),
        payment_token=token,
    )
    db_session.add(invoice)
    db_session.commit()
    return invoice


def _install(monkeypatch, provider):
    monkeypatch.setattr(provider_payments, "get_provider", lambda name: provider)
    monkeypatch.setattr(provider_payments, "provider_settings", lambda db, p: {})


def test_checkout_provider_and_invoice_boundaries(
    unauthed_client, db_session, seed_accounts, monkeypatch
):
    provider = FakeProvider(enabled=False)
    _install(monkeypatch, provider)
    assert (
        unauthed_client.post(
            "/api/payments/stripe/create-checkout-session",
            json={"payment_token": "missing"},
        ).status_code
        == 400
    )
    provider.enabled = True
    provider.configured = False
    assert (
        unauthed_client.post(
            "/api/payments/stripe/create-checkout-session",
            json={"payment_token": "missing"},
        ).status_code
        == 400
    )
    provider.configured = True
    assert (
        unauthed_client.post(
            "/api/payments/stripe/create-checkout-session",
            json={"payment_token": "missing"},
        ).status_code
        == 404
    )

    paid = _invoice(
        db_session, number="PAY-PAID", token="paid", status=InvoiceStatus.PAID
    )
    zero = _invoice(db_session, number="PAY-ZERO", token="zero", balance="0")
    assert (
        unauthed_client.post(
            "/api/payments/stripe/create-checkout-session",
            json={"payment_token": paid.payment_token},
        ).status_code
        == 400
    )
    assert (
        unauthed_client.post(
            "/api/payments/stripe/create-checkout-session",
            json={"payment_token": zero.payment_token},
        ).status_code
        == 400
    )

    ready = _invoice(db_session, number="PAY-READY", token="ready")
    checkout = unauthed_client.post(
        "/api/payments/stripe/create-checkout-session",
        json={"payment_token": ready.payment_token},
    )
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["checkout_url"].startswith("https://checkout.example")
    db_session.refresh(ready)
    assert ready.checkout_external_id == "checkout-1"
    assert ready.stripe_checkout_session_id == "checkout-1"


def test_webhook_ignored_lookup_and_recording(
    unauthed_client, db_session, seed_accounts, monkeypatch
):
    provider = FakeProvider(webhook=None)
    _install(monkeypatch, provider)
    endpoint = "/api/payments/stripe/webhook"
    assert unauthed_client.post(endpoint, content=b"{}").json() == {"status": "ignored"}
    provider.webhook = PaymentResult(status="pending", external_id="pending")
    assert unauthed_client.post(endpoint, content=b"{}").json() == {"status": "ignored"}
    provider.webhook = PaymentResult(
        status="paid", external_id="unknown", amount=Decimal("10")
    )
    assert unauthed_client.post(endpoint, content=b"{}").json() == {
        "status": "invoice_not_found"
    }

    invoice = _invoice(db_session, number="WEBHOOK", token="webhook")
    invoice.checkout_external_id = "found"
    db_session.commit()
    provider.webhook = PaymentResult(
        status="paid", external_id="found", amount=Decimal("10")
    )
    monkeypatch.setattr(
        provider_payments,
        "record_provider_payment",
        lambda *args: "recorded",
    )
    assert unauthed_client.post(endpoint, content=b"{}").json() == {
        "status": "recorded"
    }
    provider.webhook = ValueError("bad signature")
    assert unauthed_client.post(endpoint, content=b"{}").status_code == 400


def test_polling_and_payment_link_boundaries(
    client, db_session, seed_accounts, monkeypatch
):
    provider = FakeProvider()
    _install(monkeypatch, provider)
    assert client.post("/api/payments/stripe/check-status/999999").status_code == 404

    invoice = _invoice(db_session, number="POLL", token=None)
    endpoint = f"/api/payments/stripe/check-status/{invoice.id}"
    assert client.post(endpoint).json() == {"status": "no_checkout"}
    invoice.stripe_checkout_session_id = "legacy-checkout"
    db_session.commit()
    assert client.post(endpoint).json() == {
        "status": "not_paid",
        "provider_status": "pending",
    }

    provider.poll = PaymentResult(
        status="paid",
        external_id="legacy-checkout",
        amount=Decimal("10"),
        invoice_id=invoice.id,
    )
    monkeypatch.setattr(
        provider_payments,
        "record_provider_payment",
        lambda *args: "recorded",
    )
    assert client.post(endpoint).json() == {
        "status": "recorded",
        "provider_status": "paid",
    }

    assert client.get("/api/payments/payment-link/999999").status_code == 404
    invoice.payment_token = None
    db_session.commit()
    link = client.get(f"/api/payments/payment-link/{invoice.id}")
    assert link.status_code == 200
    assert "/pay/" in link.json()["url"]
    db_session.refresh(invoice)
    assert invoice.payment_token
