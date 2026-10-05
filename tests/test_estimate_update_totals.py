"""Estimate header edits cannot leave stored totals inconsistent with lines."""

from decimal import Decimal


def test_tax_rate_only_update_recalculates_totals(
    authed_client, seed_accounts, seed_customer
):
    created = authed_client.post(
        "/api/estimates",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-09-08",
            "tax_rate": "0",
            "lines": [
                {"description": "Taxable", "quantity": 1, "rate": 100},
                {
                    "description": "Exempt",
                    "quantity": 1,
                    "rate": 50,
                    "is_taxable": False,
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    updated = authed_client.put(
        f"/api/estimates/{created.json()['id']}", json={"tax_rate": "0.10"}
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert Decimal(body["subtotal"]) == Decimal("150")
    assert Decimal(body["tax_amount"]) == Decimal("10")
    assert Decimal(body["total"]) == Decimal("160")
