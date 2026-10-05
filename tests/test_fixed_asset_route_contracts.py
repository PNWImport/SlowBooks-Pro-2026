"""Fixed-asset route CRUD, filtering, and upload boundaries."""

from app.routes import fixed_assets


def _type(client, name="Equipment"):
    return client.post(
        "/api/fixed-assets/types",
        json={"name": name, "effective_life_years": 5},
    )


def _asset(client, type_id, name="Machine"):
    return client.post(
        "/api/fixed-assets",
        json={
            "name": name,
            "asset_type_id": type_id,
            "purchase_date": "2026-09-08",
            "purchase_price": 100,
        },
    )


def test_fixed_asset_list_seeds_default_type(client, seed_accounts):
    response = client.get("/api/fixed-assets/types")
    assert response.status_code == 200
    assert response.json()


def test_fixed_asset_type_and_asset_crud_filters(client):
    created_type = _type(client)
    assert created_type.status_code == 201, created_type.text
    type_id = created_type.json()["id"]
    assert _type(client).status_code == 409
    changed_type = client.put(
        f"/api/fixed-assets/types/{type_id}",
        json={"name": "Inactive Equipment", "is_active": False},
    )
    assert changed_type.status_code == 200
    assert client.put("/api/fixed-assets/types/999999", json={}).status_code == 404
    assert (
        client.get("/api/fixed-assets/types").json()
        != client.get("/api/fixed-assets/types?include_inactive=true").json()
    )

    assert _asset(client, 999999).status_code == 404
    created_asset = _asset(client, type_id)
    assert created_asset.status_code == 201, created_asset.text
    asset_id = created_asset.json()["id"]
    assert client.get(f"/api/fixed-assets/{asset_id}").status_code == 200
    assert client.get("/api/fixed-assets/999999").status_code == 404
    assert client.put("/api/fixed-assets/999999", json={"name": "x"}).status_code == 404
    changed_asset = client.put(
        f"/api/fixed-assets/{asset_id}", json={"name": "Updated Machine"}
    )
    assert changed_asset.status_code == 200
    assert changed_asset.json()["name"] == "Updated Machine"
    assert len(client.get("/api/fixed-assets?include_disposed=false").json()) == 1


def test_fixed_asset_dispose_missing_and_latin1_import(client, monkeypatch):
    assert (
        client.post(
            "/api/fixed-assets/999999/dispose",
            json={
                "disposal_date": "2026-09-08",
                "proceeds": 0,
                "deposit_account_id": 1,
            },
        ).status_code
        == 404
    )

    captured = {}

    def fake_import(db, text):
        captured["text"] = text
        return {"imported": 0, "errors": []}

    monkeypatch.setattr(fixed_assets, "import_assets_csv", fake_import)
    response = client.post(
        "/api/fixed-assets/import-csv",
        files={"file": ("assets.csv", b"name\nCaf\xe9\n", "text/csv")},
    )
    assert response.status_code == 200
    assert "Café" in captured["text"]
