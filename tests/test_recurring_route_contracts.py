"""Recurring template CRUD, validation, filtering and generation contracts."""

import pytest

from app.routes import recurring


def _create(client, customer_id, **extra):
    body = {
        "customer_id": customer_id,
        "frequency": "monthly",
        "start_date": "2026-09-08",
        "lines": [{"description": "Service", "quantity": 1, "rate": 10}],
    }
    body.update(extra)
    return client.post("/api/recurring", json=body)


def test_recurring_crud_filters_and_generate(
    authed_client, seed_accounts, seed_customer, monkeypatch
):
    first = _create(authed_client, seed_customer.id)
    assert first.status_code == 201, first.text
    second = _create(authed_client, seed_customer.id, frequency="weekly")
    assert second.status_code == 201
    fetched = authed_client.get(f"/api/recurring/{first.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["customer_name"] == seed_customer.name
    assert len(authed_client.get("/api/recurring?skip=1&limit=1").json()) == 1
    changed = authed_client.put(
        f"/api/recurring/{first.json()['id']}",
        json={
            "frequency": "quarterly",
            "is_active": False,
            "lines": [{"description": "Changed", "quantity": 2, "rate": 15}],
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["frequency"] == "quarterly"
    assert changed.json()["lines"][0]["description"] == "Changed"
    assert [
        row["id"] for row in authed_client.get("/api/recurring?active_only=true").json()
    ] == [second.json()["id"]]
    monkeypatch.setattr(recurring, "generate_due_invoices", lambda db, as_of: [3, 4])
    generated = authed_client.post("/api/recurring/generate?as_of=2026-09-08")
    assert generated.json() == {"invoices_created": 2, "invoice_ids": [3, 4]}
    assert (
        authed_client.delete(f"/api/recurring/{first.json()['id']}").status_code == 200
    )
    assert authed_client.get(f"/api/recurring/{first.json()['id']}").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"frequency": "daily"},
        {"frequency": "monthly", "end_date": "2026-09-07"},
        {"frequency": "monthly", "lines": []},
    ],
)
def test_recurring_create_validation(authed_client, seed_customer, body):
    assert _create(authed_client, seed_customer.id, **body).status_code == 422


def test_recurring_missing_routes(authed_client):
    assert _create(authed_client, 999999).status_code == 404
    assert (
        authed_client.put("/api/recurring/999999", json={"notes": "x"}).status_code
        == 404
    )
    assert authed_client.delete("/api/recurring/999999").status_code == 404


def test_recurring_update_validation(authed_client, seed_customer):
    recurring_id = _create(authed_client, seed_customer.id).json()["id"]
    endpoint = f"/api/recurring/{recurring_id}"

    assert authed_client.put(endpoint, json={"frequency": "daily"}).status_code == 422
    assert authed_client.put(endpoint, json={"frequency": None}).status_code == 422
    assert (
        authed_client.put(endpoint, json={"end_date": "2026-09-07"}).status_code == 422
    )
