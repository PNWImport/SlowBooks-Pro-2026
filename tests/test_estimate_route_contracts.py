"""Estimate route CRUD, filtering and document boundary contracts."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.routes import estimates
from app.schemas.estimates import EstimateCreate


def _create(client, customer_id, *, note="Synthetic", rate=10):
    response = client.post(
        "/api/estimates",
        json={
            "customer_id": customer_id,
            "date": "2026-09-08",
            "expiration_date": "2026-10-08",
            "notes": note,
            "lines": [{"description": "Line", "quantity": 2, "rate": rate}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_estimate_crud_filters_and_line_replacement(
    authed_client, seed_accounts, seed_customer
):
    first = _create(authed_client, seed_customer.id, note="First")
    second = _create(authed_client, seed_customer.id, note="Second", rate=20)
    fetched = authed_client.get(f"/api/estimates/{first['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["customer_name"] == seed_customer.name
    assert {
        row["id"]
        for row in authed_client.get(
            f"/api/estimates?customer_id={seed_customer.id}&status=pending"
        ).json()
    } == {first["id"], second["id"]}
    assert len(authed_client.get("/api/estimates?skip=1&limit=1").json()) == 1
    updated = authed_client.put(
        f"/api/estimates/{first['id']}",
        json={
            "notes": "Updated",
            "tax_rate": "0.10",
            "lines": [
                {"description": "Taxed", "quantity": 1, "rate": 30},
                {
                    "description": "Exempt",
                    "quantity": 1,
                    "rate": 5,
                    "is_taxable": False,
                },
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["notes"] == "Updated"
    assert len(body["lines"]) == 2
    assert Decimal(body["subtotal"]) == 35
    assert Decimal(body["tax_amount"]) == 3
    assert Decimal(body["total"]) == 38


@pytest.mark.parametrize(
    "path", ["999999", "999999/pdf", "999999/print-preview", "999999/convert"]
)
def test_estimate_missing_routes_return_404(authed_client, path):
    method = authed_client.post if path.endswith("convert") else authed_client.get
    assert method(f"/api/estimates/{path}").status_code == 404


def test_estimate_pdf_uses_renderer_and_safe_filename(
    authed_client, seed_accounts, seed_customer, monkeypatch
):
    created = _create(authed_client, seed_customer.id)
    render = []
    monkeypatch.setattr(
        estimates,
        "generate_estimate_pdf",
        lambda estimate, company: render.append((estimate.id, company))
        or b"synthetic-pdf",
    )
    response = authed_client.get(f"/api/estimates/{created['id']}/pdf")
    assert response.status_code == 200
    assert response.content == b"synthetic-pdf"
    assert response.headers["content-type"] == "application/pdf"
    assert created["estimate_number"] in response.headers["content-disposition"]
    assert render[0][0] == created["id"]


def test_estimate_print_preview_escapes_and_prints(
    authed_client, seed_accounts, seed_customer
):
    created = _create(authed_client, seed_customer.id, note="<script>bad()</script>")
    response = authed_client.get(f"/api/estimates/{created['id']}/print-preview")
    assert response.status_code == 200
    assert "window.print()" in response.text
    assert "<script>bad()</script>" not in response.text
    assert "&lt;script&gt;bad()&lt;/script&gt;" in response.text


def test_estimate_create_and_update_missing_entities(authed_client):
    response = authed_client.post(
        "/api/estimates",
        json={
            "customer_id": 999999,
            "date": date.today().isoformat(),
            "lines": [{"quantity": 1, "rate": 1}],
        },
    )
    assert response.status_code == 404
    assert (
        authed_client.put("/api/estimates/999999", json={"notes": "x"}).status_code
        == 404
    )


@pytest.mark.parametrize("mode", ["retry", "exhaust", "unrelated"])
def test_estimate_number_collision_handling(
    db_session, seed_customer, monkeypatch, mode
):
    data = EstimateCreate(
        customer_id=seed_customer.id,
        date=date(2026, 9, 8),
        lines=[{"description": "Synthetic", "quantity": 1, "rate": 1}],
    )
    real_flush = db_session.flush
    attempts = 0

    def flush(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        should_raise = mode != "retry" or attempts == 1
        if should_raise:
            message = (
                "other constraint" if mode == "unrelated" else "estimate_number unique"
            )
            raise IntegrityError("synthetic", {}, Exception(message))
        return real_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", flush)
    if mode == "retry":
        result = estimates.create_estimate(data, db_session)
        assert result.customer_name == seed_customer.name
        assert attempts >= 2
    elif mode == "unrelated":
        with pytest.raises(IntegrityError):
            estimates.create_estimate(data, db_session)
    else:
        with pytest.raises(HTTPException) as caught:
            estimates.create_estimate(data, db_session)
        assert caught.value.status_code == 503
        assert attempts == 10
