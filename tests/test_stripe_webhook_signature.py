"""The Stripe webhook is the one route reachable without a session.

`/api/stripe/webhook` is on `_AUTH_EXEMPT_EXACT` in app/main.py because
Stripe authenticates with a request signature rather than a cookie —
correct, but it means the signature check is the *only* thing standing
between the open internet and a handler that records payments against
invoices. That check had no test.

These pin both rejection paths, so a refactor that drops the
`construct_event` call (or catches its exception too broadly) fails here
rather than in production, where the symptom would be forged payments
marking invoices paid.
"""

import json


def _post_webhook(client, body: dict, signature: str | None = None):
    headers = {"stripe-signature": signature} if signature is not None else {}
    return client.post(
        "/api/stripe/webhook",
        content=json.dumps(body).encode(),
        headers=headers,
    )


FORGED_EVENT = {
    "type": "checkout.session.completed",
    "data": {"object": {"id": "cs_forged_123", "metadata": {"invoice_id": "1"}}},
}


def test_webhook_rejected_when_secret_not_configured(client):
    """No configured secret means nothing can be verified — refuse, don't
    fall through to processing."""
    resp = _post_webhook(client, FORGED_EVENT, signature="t=1,v1=deadbeef")
    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"].lower()


def test_webhook_rejects_bad_signature(client):
    """Secret configured, signature garbage — must 400."""
    client.put("/api/settings", json={"stripe_webhook_secret": "whsec_test_secret"})
    resp = _post_webhook(client, FORGED_EVENT, signature="t=1,v1=not_a_real_sig")
    assert resp.status_code == 400
    assert "signature" in resp.json()["detail"].lower()


def test_webhook_rejects_missing_signature_header(client):
    """A bare POST with no signature header at all is still rejected."""
    client.put("/api/settings", json={"stripe_webhook_secret": "whsec_test_secret"})
    resp = _post_webhook(client, FORGED_EVENT)
    assert resp.status_code == 400


def test_forged_event_creates_no_payment(client, db_session):
    """The point of the signature check: an unsigned 'paid' event must not
    record a payment."""
    from app.models.payments import Payment

    client.put("/api/settings", json={"stripe_webhook_secret": "whsec_test_secret"})
    _post_webhook(client, FORGED_EVENT, signature="t=1,v1=forged")

    assert (
        db_session.query(Payment).filter(Payment.reference == "cs_forged_123").first()
        is None
    ), "a forged webhook recorded a payment"
