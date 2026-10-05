"""Square payment-link, webhook and polling boundaries with mocked transport."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.payments import square

SETTINGS = {
    "square_environment": "sandbox",
    "square_access_token": "square-token",
    "square_location_id": "location-1",
    "square_webhook_signature_key": "signing-key",
    "square_notification_url": "https://books.test/api/payments/square/webhook",
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
        id=9,
        invoice_number="INV-9",
        balance_due=Decimal("7.895"),
        payment_token="payment-token",
    )


def test_request_helpers_select_environment_sign_and_round_amount():
    request = square.build_payment_link_request(
        _invoice(), SETTINGS, "https://books.test", idempotency_key="stable"
    )
    assert request["url"].startswith("https://connect.squareupsandbox.com")
    assert request["headers"]["Authorization"] == "Bearer square-token"
    assert request["json"]["quick_pay"]["price_money"]["amount"] == 790
    assert request["json"]["idempotency_key"] == "stable"
    assert square.api_base(SETTINGS | {"square_environment": "production"}).endswith(
        "squareup.com"
    )
    assert square.api_base(
        SETTINGS | {"square_environment": "other"}
    ) == square.api_base({})
    assert square.build_get_order_request("order", SETTINGS)["method"] == "GET"
    assert square.webhook_signature("key", "url", b"body") == square.webhook_signature(
        "key", "url", b"body"
    )


def test_checkout_configuration_and_response_boundaries(monkeypatch):
    provider = square.SquareProvider()
    assert provider.is_configured(SETTINGS) is True
    assert provider.is_configured({}) is False
    monkeypatch.setattr(
        square._http, "send", lambda *_args, **_kwargs: Response(500, text="nope")
    )
    with pytest.raises(ValueError, match="link creation failed"):
        provider.create_checkout(_invoice(), SETTINGS, "https://books.test")
    monkeypatch.setattr(
        square._http,
        "send",
        lambda *_args, **_kwargs: Response(
            201, {"payment_link": {"url": "https://pay"}}
        ),
    )
    with pytest.raises(ValueError, match="missing url/order_id"):
        provider.create_checkout(_invoice(), SETTINGS, "https://books.test")
    monkeypatch.setattr(
        square._http,
        "send",
        lambda *_args, **_kwargs: Response(
            200, {"payment_link": {"url": "https://pay", "order_id": "order-1"}}
        ),
    )
    checkout = provider.create_checkout(_invoice(), SETTINGS, "https://books.test")
    assert (checkout.url, checkout.external_id) == ("https://pay", "order-1")


def test_webhook_configuration_signature_payload_and_payment_filters():
    provider = square.SquareProvider()
    with pytest.raises(ValueError, match="signature key"):
        provider.verify_webhook(
            b"{}", {}, SETTINGS | {"square_webhook_signature_key": ""}
        )
    with pytest.raises(ValueError, match="notification_url"):
        provider.verify_webhook(b"{}", {}, SETTINGS | {"square_notification_url": ""})
    with pytest.raises(ValueError, match="Invalid webhook signature"):
        provider.verify_webhook(b"{}", {}, SETTINGS)
    bad_body = b"not-json"
    bad_headers = {
        "x-square-hmacsha256-signature": square.webhook_signature(
            SETTINGS["square_webhook_signature_key"],
            SETTINGS["square_notification_url"],
            bad_body,
        )
    }
    with pytest.raises(ValueError, match="Invalid webhook payload"):
        provider.verify_webhook(bad_body, bad_headers, SETTINGS)

    def deliver(event):
        body = json.dumps(event).encode()
        headers = {
            "x-square-hmacsha256-signature": square.webhook_signature(
                SETTINGS["square_webhook_signature_key"],
                SETTINGS["square_notification_url"],
                body,
            )
        }
        return provider.verify_webhook(body, headers, SETTINGS)

    assert deliver({"type": "other"}) is None
    assert (
        deliver(
            {
                "type": "payment.updated",
                "data": {"object": {"payment": {"status": "PENDING"}}},
            }
        )
        is None
    )
    assert (
        deliver(
            {
                "type": "payment.updated",
                "data": {"object": {"payment": {"status": "COMPLETED"}}},
            }
        )
        is None
    )
    result = deliver(
        {
            "type": "payment.updated",
            "data": {
                "object": {
                    "payment": {
                        "status": "COMPLETED",
                        "order_id": "order-2",
                        "amount_money": {"amount": 250},
                    }
                }
            },
        }
    )
    assert (result.status, result.external_id, result.amount, result.invoice_id) == (
        "paid",
        "order-2",
        Decimal("2.5"),
        None,
    )


@pytest.mark.parametrize(
    ("response", "status", "amount"),
    [
        (Response(503), "unknown", None),
        (Response(200, {"order": {"state": "CANCELED"}}), "cancelled", None),
        (
            Response(
                200, {"order": {"state": "COMPLETED", "total_money": {"amount": 400}}}
            ),
            "paid",
            Decimal("4"),
        ),
        (
            Response(
                200,
                {
                    "order": {
                        "state": "OPEN",
                        "tenders": [{}],
                        "net_amount_due_money": {"amount": 0},
                    }
                },
            ),
            "paid",
            None,
        ),
        (Response(200, {"order": {"state": "OPEN", "tenders": []}}), "pending", None),
    ],
)
def test_poll_status_and_square_paid_shapes(monkeypatch, response, status, amount):
    monkeypatch.setattr(square._http, "send", lambda *_args, **_kwargs: response)
    result = square.SquareProvider().poll_status("order-poll", SETTINGS)
    assert (result.status, result.amount) == (status, amount)
    assert square._order_is_paid({"state": "DRAFT"}) is False
