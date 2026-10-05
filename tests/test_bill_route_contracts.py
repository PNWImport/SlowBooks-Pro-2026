"""Bill CRUD, account selection, numbering, posting and void contracts."""

from decimal import Decimal

from app.models.bills import Bill
from app.models.contacts import Vendor
from app.models.items import Item, ItemType
from app.models.transactions import Transaction, TransactionLine
from tests.test_inventory_integration import _seed_stock, _seed_vendor, _tracked_item


def _vendor(client, name="Synthetic Vendor", **extra):
    response = client.post("/api/vendors", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _bill(client, vendor_id, account_id, **extra):
    body = {
        "vendor_id": vendor_id,
        "date": "2026-09-08",
        "lines": [
            {"account_id": account_id, "description": "Line", "quantity": 1, "rate": 10}
        ],
    }
    body.update(extra)
    response = client.post("/api/bills", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_bill_crud_filters_default_number_and_void_guards(
    authed_client, db_session, seed_accounts
):
    vendor = _vendor(authed_client, "Gin Kee")
    first = _bill(authed_client, vendor["id"], seed_accounts["6000"].id)
    second = _bill(authed_client, vendor["id"], seed_accounts["6000"].id)
    third = _bill(authed_client, vendor["id"], seed_accounts["6000"].id)
    assert first["bill_number"] == "20260908-GK"
    assert second["bill_number"] == "20260908-GK-2"
    assert third["bill_number"] == "20260908-GK-3"
    fetched = authed_client.get(f"/api/bills/{first['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["vendor_name"] == "Gin Kee"
    listed = authed_client.get(
        f"/api/bills?vendor_id={vendor['id']}&status=unpaid"
    ).json()
    assert {row["id"] for row in listed} == {first["id"], second["id"], third["id"]}
    assert len(authed_client.get("/api/bills?skip=1&limit=1").json()) == 1
    duplicate = authed_client.post(
        "/api/bills",
        json={
            "vendor_id": vendor["id"],
            "bill_number": first["bill_number"],
            "date": "2026-09-08",
            "lines": [{"quantity": 1, "rate": 1}],
        },
    )
    assert duplicate.status_code == 409
    assert authed_client.get("/api/bills/999999").status_code == 404
    assert authed_client.post("/api/bills/999999/void").status_code == 404
    voided = authed_client.post(f"/api/bills/{first['id']}/void")
    assert voided.status_code == 200, voided.text
    assert authed_client.post(f"/api/bills/{first['id']}/void").status_code == 400
    stored = db_session.get(Bill, second["id"])
    stored.amount_paid = Decimal("1")
    db_session.commit()
    assert authed_client.post(f"/api/bills/{second['id']}/void").status_code == 400


def test_bill_account_precedence_tax_zero_and_balanced_void(
    authed_client, db_session, seed_accounts
):
    vendor = Vendor(
        name="Fallback Vendor",
        is_active=True,
        default_expense_account_id=seed_accounts["6100"].id,
    )
    item = Item(
        name="Expense Item",
        item_type=ItemType.SERVICE,
        expense_account_id=seed_accounts["6200"].id,
    )
    db_session.add_all([vendor, item])
    db_session.commit()
    response = authed_client.post(
        "/api/bills",
        json={
            "vendor_id": vendor.id,
            "bill_number": "MAP-1",
            "date": "2026-09-08",
            "tax_rate": "0.10",
            "lines": [
                {"item_id": item.id, "description": "Item", "quantity": 1, "rate": 10},
                {"description": "Vendor", "quantity": 1, "rate": 20},
                {
                    "account_id": seed_accounts["6300"].id,
                    "description": "Explicit",
                    "quantity": 1,
                    "rate": 30,
                },
                {"description": "Zero", "quantity": 1, "rate": 0},
            ],
        },
    )
    assert response.status_code == 201, response.text
    bill = db_session.get(Bill, response.json()["id"])
    assert [line.account_id for line in bill.lines[:3]] == [
        seed_accounts["6200"].id,
        seed_accounts["6100"].id,
        seed_accounts["6300"].id,
    ]
    assert bill.total == Decimal("66")
    original = (
        db_session.query(TransactionLine)
        .filter_by(transaction_id=bill.transaction_id)
        .all()
    )
    assert (
        sum(line.debit for line in original)
        == sum(line.credit for line in original)
        == 66
    )
    assert authed_client.post(f"/api/bills/{bill.id}/void").status_code == 200
    reversal = (
        db_session.query(Transaction)
        .filter_by(source_type="bill_void", source_id=bill.id)
        .one()
    )
    reversed_lines = (
        db_session.query(TransactionLine).filter_by(transaction_id=reversal.id).all()
    )
    assert (
        sum(line.debit for line in reversed_lines)
        == sum(line.credit for line in reversed_lines)
        == 66
    )


def test_missing_vendor_rejected(authed_client):
    response = authed_client.post(
        "/api/bills",
        json={
            "vendor_id": 999999,
            "date": "2026-09-08",
            "lines": [{"quantity": 1, "rate": 1}],
        },
    )
    assert response.status_code == 404


def test_bill_uses_chart_default_expense(authed_client, db_session, seed_accounts):
    vendor = _vendor(authed_client, "Chart default")
    bill = _bill(authed_client, vendor["id"], None)
    stored = db_session.get(Bill, bill["id"])
    assert stored.lines[0].account_id == seed_accounts["6000"].id


def test_void_bill_reverses_inventory_receipt(authed_client, db_session, seed_accounts):
    vendor = _seed_vendor(db_session)
    item = _tracked_item(db_session, seed_accounts, name="Void bill stock")
    bill = _seed_stock(authed_client, vendor.id, item.id, 5, 10, "VOID-BILL")
    db_session.expire_all()
    assert item.quantity_on_hand == 5
    response = authed_client.post(f"/api/bills/{bill['id']}/void")
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert item.quantity_on_hand == 0
