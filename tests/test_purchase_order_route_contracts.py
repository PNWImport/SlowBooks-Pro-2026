"""Purchase-order CRUD, totals, numbering, and conversion contracts."""

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.routes import purchase_orders
from app.schemas.purchase_orders import POCreate


def _vendor(client, name="PO Vendor", **extra):
    body = {"name": name}
    body.update(extra)
    response = client.post("/api/vendors", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _po(client, vendor_id, **extra):
    body = {
        "vendor_id": vendor_id,
        "date": "2026-09-08",
        "lines": [{"description": "Materials", "quantity": 2, "rate": 10}],
    }
    body.update(extra)
    return client.post("/api/purchase-orders", json=body)


def test_purchase_order_crud_filters_and_totals(client):
    vendor = _vendor(client)
    replacement = _vendor(client, "Replacement")
    created = _po(client, vendor["id"])
    assert created.status_code == 201, created.text
    purchase_order = created.json()
    endpoint = f"/api/purchase-orders/{purchase_order['id']}"

    fetched = client.get(endpoint)
    assert fetched.status_code == 200
    assert fetched.json()["vendor_name"] == vendor["name"]
    assert (
        len(
            client.get(
                f"/api/purchase-orders?vendor_id={vendor['id']}&status=draft&limit=1"
            ).json()
        )
        == 1
    )
    changed = client.put(
        endpoint,
        json={
            "vendor_id": replacement["id"],
            "status": "sent",
            "tax_rate": 0.1,
            "lines": [{"description": "Changed", "quantity": 3, "rate": 10}],
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["subtotal"] == "30.00"
    assert changed.json()["tax_amount"] == "3.00"
    assert changed.json()["total"] == "33.00"
    tax_only = client.put(endpoint, json={"tax_rate": 0.2})
    assert tax_only.status_code == 200
    assert tax_only.json()["tax_amount"] == "6.00"
    assert tax_only.json()["total"] == "36.00"

    assert _po(client, 999999).status_code == 404
    assert client.get("/api/purchase-orders/999999").status_code == 404
    assert (
        client.put("/api/purchase-orders/999999", json={"notes": "x"}).status_code
        == 404
    )
    assert client.put(endpoint, json={"vendor_id": 999999}).status_code == 404
    assert client.put(endpoint, json={"status": "invalid"}).status_code == 422
    assert _po(client, vendor["id"], lines=[]).status_code == 422


def test_purchase_order_number_exhaustion_returns_service_unavailable(
    client, monkeypatch
):
    vendor = _vendor(client)
    first = _po(client, vendor["id"])
    assert first.status_code == 201
    monkeypatch.setattr(
        purchase_orders, "next_po_number", lambda db: first.json()["po_number"]
    )
    exhausted = _po(client, vendor["id"])
    assert exhausted.status_code == 503


def test_purchase_order_unrelated_integrity_error_is_not_retried(monkeypatch):
    class FakeDB:
        def query(self, *args):
            return self

        def filter(self, *args):
            return self

        def first(self):
            return SimpleNamespace(id=1, name="Vendor")

        def add(self, value):
            pass

        def flush(self):
            raise IntegrityError("insert", {}, Exception("other constraint"))

    monkeypatch.setattr(purchase_orders, "next_po_number", lambda db: "PO-1")
    data = POCreate(
        vendor_id=1,
        date=date(2026, 9, 8),
        lines=[{"description": "Line", "quantity": 1, "rate": 1}],
    )
    with pytest.raises(IntegrityError, match="other constraint"):
        purchase_orders.create_po(data, FakeDB())


def test_purchase_order_conversion_account_precedence_and_tax(client, seed_accounts):
    vendor = _vendor(
        client,
        default_expense_account_id=seed_accounts["6000"].id,
    )
    item = client.post(
        "/api/items",
        json={
            "name": "PO Expense Item",
            "item_type": "service",
            "expense_account_id": seed_accounts["6100"].id,
        },
    )
    assert item.status_code == 201, item.text
    created = _po(
        client,
        vendor["id"],
        tax_rate=0.1,
        lines=[
            {"item_id": item.json()["id"], "quantity": 1, "rate": 10},
            {"description": "Vendor fallback", "quantity": 1, "rate": 20},
        ],
    )
    assert created.status_code == 201, created.text
    endpoint = f"/api/purchase-orders/{created.json()['id']}/convert-to-bill"
    converted = client.post(endpoint)
    assert converted.status_code == 200, converted.text
    assert client.post(endpoint).status_code == 400
    assert client.post("/api/purchase-orders/999999/convert-to-bill").status_code == 404


def test_purchase_order_conversion_rejects_inventory_without_asset_account(client):
    vendor = _vendor(client)
    item = client.post(
        "/api/items",
        json={
            "name": "Unmapped Inventory",
            "item_type": "product",
            "track_inventory": True,
        },
    )
    assert item.status_code == 201, item.text
    created = _po(
        client,
        vendor["id"],
        lines=[{"item_id": item.json()["id"], "quantity": 1, "rate": 10}],
    )
    response = client.post(
        f"/api/purchase-orders/{created.json()['id']}/convert-to-bill"
    )
    assert response.status_code == 400
    assert "inventory-tracked" in response.json()["detail"]
