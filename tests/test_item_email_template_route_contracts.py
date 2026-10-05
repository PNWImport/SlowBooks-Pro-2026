"""Item and email-template route CRUD/filter/error contracts."""

from decimal import Decimal

from app.models.items import Item, ItemType
from app.routes import items


def test_item_crud_filters_movements_and_adjustment_edges(
    client, db_session, monkeypatch
):
    created = client.post(
        "/api/items",
        json={"name": "Route Widget", "item_type": "product", "track_inventory": False},
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    assert (
        len(
            client.get(
                "/api/items?active_only=true&item_type=product&search=Widget"
            ).json()
        )
        == 1
    )
    assert client.get(f"/api/items/{item_id}").status_code == 200
    assert client.get("/api/items/999999").status_code == 404
    assert client.get("/api/items/999999/movements").status_code == 404
    assert client.get(f"/api/items/{item_id}/movements").json() == []
    assert (
        client.post(
            f"/api/items/{item_id}/adjust", json={"quantity_delta": 1}
        ).status_code
        == 400
    )

    changed = client.put(
        f"/api/items/{item_id}",
        json={"name": "Changed Widget", "track_inventory": True, "reorder_point": 3},
    )
    assert changed.status_code == 200
    monkeypatch.setattr(items, "record_adjustment", lambda *args, **kwargs: None)
    assert (
        client.post(
            f"/api/items/{item_id}/adjust", json={"quantity_delta": 0}
        ).status_code
        == 400
    )
    assert client.delete(f"/api/items/{item_id}").status_code == 200

    legacy = Item(
        name="Legacy Negative Reorder",
        item_type=ItemType.PRODUCT,
        track_inventory=True,
        is_active=True,
        quantity_on_hand=Decimal("-1"),
        reorder_point=Decimal("-10"),
        avg_cost=Decimal("1"),
    )
    db_session.add(legacy)
    db_session.commit()
    low = client.get("/api/items/low-stock").json()
    assert Decimal(next(row for row in low if row["id"] == legacy.id)["shortage"]) == 0


def test_email_template_crud_seed_and_missing(client):
    assert client.post("/api/email-templates/seed-defaults").json()["created"] > 0
    assert client.post("/api/email-templates/seed-defaults").json()["created"] == 0
    body = {
        "name": "custom_route_template",
        "subject_template": "Subject",
        "body_template": "Body",
        "template_type": "custom",
    }
    created = client.post("/api/email-templates", json=body)
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    assert client.post("/api/email-templates", json=body).status_code == 400
    assert client.get(f"/api/email-templates/{template_id}").status_code == 200
    assert client.get("/api/email-templates/999999").status_code == 404
    assert (
        client.put(
            "/api/email-templates/999999", json={"subject_template": "x"}
        ).status_code
        == 404
    )
    changed = client.put(
        f"/api/email-templates/{template_id}", json={"subject_template": "Changed"}
    )
    assert changed.status_code == 200
    assert changed.json()["subject_template"] == "Changed"
    assert client.get("/api/email-templates").status_code == 200
    assert client.delete(f"/api/email-templates/{template_id}").status_code == 200
    assert client.delete(f"/api/email-templates/{template_id}").status_code == 404
