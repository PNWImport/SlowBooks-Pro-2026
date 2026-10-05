"""Bill due dates use the same terms semantics as receivable documents."""

from datetime import date, timedelta

import pytest


@pytest.mark.parametrize(
    "terms, days", [("Due on receipt", 0), ("Net 15", 15), ("Unknown", 30)]
)
def test_bill_due_date_from_terms(authed_client, seed_accounts, terms, days):
    vendor = authed_client.post("/api/vendors", json={"name": f"Terms {terms}"})
    assert vendor.status_code == 201, vendor.text
    response = authed_client.post(
        "/api/bills",
        json={
            "vendor_id": vendor.json()["id"],
            "date": "2026-09-08",
            "terms": terms,
            "lines": [
                {
                    "account_id": seed_accounts["6000"].id,
                    "description": "Synthetic",
                    "quantity": 1,
                    "rate": 10,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    assert (
        response.json()["due_date"]
        == (date(2026, 9, 8) + timedelta(days=days)).isoformat()
    )
