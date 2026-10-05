"""Stripe adapter contracts with every SDK call mocked."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.payments import stripe as stripe_provider

SETTINGS = {"stripe_secret_key": "sk-boundary", "stripe_webhook_secret": "whsec"}


def _invoice(email=None):
    customer = SimpleNamespace(email=email) if email is not None else None
    return SimpleNamespace(
        id=8,
        invoice_number="INV-8",
        balance_due=Decimal("12.34"),
        payment_token="token-8",
        customer=customer,
    )


def test_checkout_sets_key_and_preserves_optional_customer_email(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        stripe_provider.stripe.checkout.Session,
        "create",
        lambda **kwargs: seen.update(kwargs)
        or SimpleNamespace(id="cs_1", url="https://stripe.test/1"),
    )
    created = stripe_provider.StripeProvider().create_checkout(
        _invoice("payer@example.test"), SETTINGS, "https://books.test"
    )
    assert stripe_provider.stripe.api_key == "sk-boundary"
    assert (created.external_id, created.url) == ("cs_1", "https://stripe.test/1")
    assert seen["line_items"][0]["price_data"]["unit_amount"] == 1234
    assert seen["customer_email"] == "payer@example.test"
    assert seen["metadata"] == {"invoice_id": "8", "payment_token": "token-8"}
    assert stripe_provider.StripeProvider().is_configured(SETTINGS) is True
    assert stripe_provider.StripeProvider().is_configured({}) is False


def test_webhook_requires_valid_signature_and_filters_events(monkeypatch):
    with pytest.raises(ValueError, match="Webhook secret"):
        stripe_provider.StripeProvider().verify_webhook(
            b"{}", {}, SETTINGS | {"stripe_webhook_secret": ""}
        )
    monkeypatch.setattr(
        stripe_provider.stripe.Webhook,
        "construct_event",
        lambda *_args: (_ for _ in ()).throw(Exception("bad")),
    )
    with pytest.raises(ValueError, match="Invalid webhook"):
        stripe_provider.StripeProvider().verify_webhook(b"{}", {}, SETTINGS)

    monkeypatch.setattr(
        stripe_provider.stripe.Webhook,
        "construct_event",
        lambda *_args: {"type": "checkout.session.expired", "data": {"object": {}}},
    )
    assert stripe_provider.StripeProvider().verify_webhook(b"{}", {}, SETTINGS) is None
    monkeypatch.setattr(
        stripe_provider.stripe.Webhook,
        "construct_event",
        lambda *_args: {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_2",
                    "amount_total": 321,
                    "metadata": {"invoice_id": "8"},
                }
            },
        },
    )
    result = stripe_provider.StripeProvider().verify_webhook(b"{}", {}, SETTINGS)
    assert (result.status, result.amount, result.invoice_id) == (
        "paid",
        Decimal("3.21"),
        8,
    )


@pytest.mark.parametrize(
    ("session", "status", "amount"),
    [
        (
            {
                "payment_status": "paid",
                "status": "complete",
                "amount_total": 200,
                "metadata": {"invoice_id": "8"},
            },
            "paid",
            Decimal("2"),
        ),
        (
            {
                "payment_status": "unpaid",
                "status": "expired",
                "amount_total": 200,
                "metadata": {},
            },
            "cancelled",
            None,
        ),
        (
            {
                "payment_status": "unpaid",
                "status": "open",
                "amount_total": None,
                "metadata": {},
            },
            "pending",
            None,
        ),
    ],
)
def test_poll_maps_stripe_states(monkeypatch, session, status, amount):
    monkeypatch.setattr(
        stripe_provider.stripe.checkout.Session, "retrieve", lambda _: session
    )
    result = stripe_provider.StripeProvider().poll_status("cs_poll", SETTINGS)
    assert (result.status, result.amount) == (status, amount)
    assert result.invoice_id == (8 if status == "paid" else None)
