"""PayPal transport failures and non-happy payment state boundaries."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.payments import paypal as paypal
from app.services import payments

SETTINGS = {
    "paypal_environment": "sandbox",
    "paypal_client_id": "boundary-client",
    "paypal_client_secret": "boundary-secret",
    "paypal_webhook_id": "WH-boundary",
}


class Response:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _invoice():
    return SimpleNamespace(
        id=5,
        invoice_number="INV-5",
        balance_due=Decimal("9.99"),
        payment_token="pay-token",
        date=date(2026, 1, 1),
    )


def _token():
    return Response(payload={"access_token": "token", "expires_in": 3600})


@pytest.fixture(autouse=True)
def clear_token_cache():
    paypal._token_cache.clear()


def test_auth_and_checkout_failures_are_clear(monkeypatch):
    monkeypatch.setattr(paypal._http, "send", lambda *_args, **_kwargs: Response(401))
    with pytest.raises(ValueError, match="auth failed"):
        paypal.PayPalProvider()._access_token(SETTINGS)

    responses = [_token(), Response(422, text="bad order")]
    monkeypatch.setattr(
        paypal._http, "send", lambda *_args, **_kwargs: responses.pop(0)
    )
    with pytest.raises(ValueError, match="order creation failed"):
        paypal.PayPalProvider().create_checkout(
            _invoice(), SETTINGS, "https://books.test"
        )

    paypal._token_cache.clear()
    responses = [_token(), Response(201, {"id": "order-without-link"})]
    monkeypatch.setattr(
        paypal._http, "send", lambda *_args, **_kwargs: responses.pop(0)
    )
    with pytest.raises(ValueError, match="no approval link"):
        paypal.PayPalProvider().create_checkout(
            _invoice(), SETTINGS, "https://books.test"
        )

    paypal._token_cache.clear()
    responses = [
        _token(),
        Response(
            200,
            {"id": "ok", "links": [{"rel": "payer-action", "href": "https://approve"}]},
        ),
    ]
    monkeypatch.setattr(
        paypal._http, "send", lambda *_args, **_kwargs: responses.pop(0)
    )
    checkout = paypal.PayPalProvider().create_checkout(
        _invoice(), SETTINGS, "https://books.test"
    )
    assert (checkout.external_id, checkout.url) == ("ok", "https://approve")


def test_provider_registry_lists_its_three_stable_singletons():
    assert [provider.name for provider in payments.all_providers()] == [
        "stripe",
        "paypal",
        "square",
    ]


def test_webhook_configuration_and_payload_errors(monkeypatch):
    with pytest.raises(ValueError, match="not configured"):
        paypal.PayPalProvider().verify_webhook(
            b"{}", {}, {"paypal_webhook_id": "present"}
        )

    monkeypatch.setattr(paypal._http, "send", lambda *_args, **_kwargs: _token())
    with pytest.raises(ValueError, match="Invalid webhook payload"):
        paypal.PayPalProvider().verify_webhook(b"not-json", {}, SETTINGS)


def test_poll_unknown_cancelled_and_order_extraction_edges(monkeypatch):
    responses = [_token(), Response(503)]
    monkeypatch.setattr(
        paypal._http, "send", lambda *_args, **_kwargs: responses.pop(0)
    )
    assert paypal.PayPalProvider().poll_status("missing", SETTINGS).status == "unknown"

    paypal._token_cache.clear()
    responses = [_token(), Response(200, {"status": "VOIDED"})]
    monkeypatch.setattr(
        paypal._http, "send", lambda *_args, **_kwargs: responses.pop(0)
    )
    assert paypal.PayPalProvider().poll_status("void", SETTINGS).status == "cancelled"

    assert paypal._order_invoice_id({"purchase_units": [{"custom_id": "bad"}]}) is None
    assert paypal._order_invoice_id({}) is None
    assert paypal._order_captured_amount(
        {"purchase_units": [{"amount": {"value": "4.50"}}]}
    ) == Decimal("4.50")
    assert paypal._order_captured_amount({}) is None
