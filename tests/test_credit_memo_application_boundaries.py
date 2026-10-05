"""Credits can only reduce a positive balance for the same customer."""

from decimal import Decimal

import pytest

from app.models.credit_memos import CreditMemo
from app.models.invoices import Invoice
from tests.test_invoice_posting import _create_invoice


def _credit(client, customer_id, amount=50):
    response = client.post(
        "/api/credit-memos",
        json={
            "customer_id": customer_id,
            "date": "2026-09-08",
            "lines": [{"description": "Credit", "quantity": 1, "rate": amount}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("amount", [0, -1, "0.001", "0.005", "1.001"])
def test_invalid_credit_application_amount_rejected(
    authed_client, db_session, seed_accounts, seed_customer, amount
):
    credit = _credit(authed_client, seed_customer.id)
    invoice = _create_invoice(authed_client, seed_customer.id)
    response = authed_client.post(
        f"/api/credit-memos/{credit['id']}/apply",
        json={"invoice_id": invoice["id"], "amount": amount},
    )
    assert response.status_code == 422
    db_session.expire_all()
    assert db_session.get(CreditMemo, credit["id"]).balance_remaining == Decimal("50")
    assert db_session.get(Invoice, invoice["id"]).balance_due == Decimal("100")


def test_cross_customer_credit_application_rejected_atomically(
    authed_client, db_session, seed_accounts, seed_customer
):
    other = authed_client.post("/api/customers", json={"name": "Other customer"})
    assert other.status_code == 201, other.text
    credit = _credit(authed_client, seed_customer.id)
    invoice = _create_invoice(authed_client, other.json()["id"])
    response = authed_client.post(
        f"/api/credit-memos/{credit['id']}/apply",
        json={"invoice_id": invoice["id"], "amount": 25},
    )
    assert response.status_code == 400
    assert "customer" in response.json()["detail"].lower()
    db_session.expire_all()
    assert db_session.get(CreditMemo, credit["id"]).balance_remaining == Decimal("50")
    assert db_session.get(Invoice, invoice["id"]).balance_due == Decimal("100")


@pytest.mark.parametrize("reference", ["missing", "other_customer"])
def test_original_invoice_reference_must_match_customer(
    authed_client, seed_accounts, seed_customer, reference
):
    invoice_id = 999999
    if reference == "other_customer":
        other = authed_client.post("/api/customers", json={"name": "Reference owner"})
        assert other.status_code == 201
        invoice_id = _create_invoice(authed_client, other.json()["id"])["id"]
    response = authed_client.post(
        "/api/credit-memos",
        json={
            "customer_id": seed_customer.id,
            "original_invoice_id": invoice_id,
            "date": "2026-09-08",
            "lines": [{"description": "Credit", "quantity": 1, "rate": 10}],
        },
    )
    assert response.status_code == (404 if reference == "missing" else 400)
