"""Cost-type and equipment route boundary contracts."""

from app.models.job_costing import CostType
from app.routes import job_costing


def test_cost_type_crud_guards(authed_client, seed_accounts):
    listed = authed_client.get("/api/cost-types")
    assert listed.status_code == 200
    standard = listed.json()[0]
    created = authed_client.post(
        "/api/cost-types",
        json={
            "code": "travel",
            "name": "Travel",
            "default_account_id": seed_accounts["6000"].id,
        },
    )
    assert created.status_code == 201, created.text
    type_id = created.json()["id"]
    assert created.json()["default_account_name"]
    assert (
        authed_client.post(
            "/api/cost-types", json={"code": "travel", "name": "Again"}
        ).status_code
        == 409
    )
    assert (
        authed_client.post(
            "/api/cost-types",
            json={"code": "bad_account", "name": "Bad", "default_account_id": 999999},
        ).status_code
        == 404
    )
    assert (
        authed_client.put("/api/cost-types/999999", json={"name": "x"}).status_code
        == 404
    )
    assert (
        authed_client.put(
            f"/api/cost-types/{type_id}", json={"default_account_id": 999999}
        ).status_code
        == 404
    )
    assert (
        authed_client.put(
            f"/api/cost-types/{type_id}", json={"name": "   "}
        ).status_code
        == 422
    )
    updated = authed_client.put(
        f"/api/cost-types/{type_id}",
        json={"name": "Travel updated", "is_active": False},
    )
    assert updated.status_code == 200
    assert all(
        row["id"] != type_id for row in authed_client.get("/api/cost-types").json()
    )
    assert any(
        row["id"] == type_id
        for row in authed_client.get("/api/cost-types?include_inactive=true").json()
    )
    assert authed_client.delete(f"/api/cost-types/{standard['id']}").status_code == 400
    assert authed_client.delete("/api/cost-types/999999").status_code == 404
    assert authed_client.delete(f"/api/cost-types/{type_id}").status_code == 200


def test_equipment_crud_guards(authed_client, seed_accounts):
    created = authed_client.post(
        "/api/equipment",
        json={
            "name": "Excavator",
            "code": "EX-1",
            "hourly_rate": 125,
            "recovery_account_id": seed_accounts["4100"].id,
        },
    )
    assert created.status_code == 201, created.text
    equipment_id = created.json()["id"]
    assert len(authed_client.get("/api/equipment").json()) == 1
    assert (
        authed_client.post(
            "/api/equipment", json={"name": "Bad", "recovery_account_id": 999999}
        ).status_code
        == 404
    )
    assert (
        authed_client.put("/api/equipment/999999", json={"name": "x"}).status_code
        == 404
    )
    assert (
        authed_client.put(
            f"/api/equipment/{equipment_id}", json={"recovery_account_id": 999999}
        ).status_code
        == 404
    )
    updated = authed_client.put(
        f"/api/equipment/{equipment_id}", json={"is_active": False, "hourly_rate": 130}
    )
    assert updated.status_code == 200
    assert authed_client.get("/api/equipment").json() == []
    assert len(authed_client.get("/api/equipment?include_inactive=true").json()) == 1
    assert authed_client.delete("/api/equipment/999999").status_code == 404
    assert authed_client.delete(f"/api/equipment/{equipment_id}").status_code == 200


def test_job_cost_validation_and_missing_routes(
    authed_client, seed_accounts, seed_customer
):
    job = authed_client.post(
        "/api/jobs", json={"customer_id": seed_customer.id, "name": "Validation"}
    ).json()
    authed_client.post("/api/cost-types/setup-offsets")
    base = {"date": "2026-09-08", "lines": [{"amount": 10}]}
    assert (
        authed_client.post(
            "/api/job-costs", json={**base, "job_id": 999999}
        ).status_code
        == 404
    )
    assert authed_client.post("/api/job-costs", json=base).status_code == 422
    assert (
        authed_client.post(
            "/api/job-costs",
            json={
                "date": "2026-09-08",
                "job_id": job["id"],
                "lines": [{"job_id": 999999, "amount": 10}],
            },
        ).status_code
        == 404
    )
    assert (
        authed_client.post(
            "/api/job-costs",
            json={
                "date": "2026-09-08",
                "job_id": job["id"],
                "lines": [{"cost_code_id": 999999, "amount": 10}],
            },
        ).status_code
        == 404
    )
    assert (
        authed_client.post(
            "/api/job-costs",
            json={
                "date": "2026-09-08",
                "job_id": job["id"],
                "lines": [{"cost_type": "unknown", "amount": 10}],
            },
        ).status_code
        == 422
    )
    assert authed_client.get("/api/job-costs/999999").status_code == 404
    assert authed_client.post("/api/job-costs/999999/void").status_code == 404


def test_allocation_without_jobs_rejected(authed_client, seed_accounts):
    authed_client.post("/api/cost-types/setup-offsets")
    response = authed_client.post(
        "/api/job-costs/allocate",
        json={"date": "2026-09-08", "amount": 10, "method": "equal"},
    )
    assert response.status_code == 422
    assert "No jobs" in response.json()["detail"]


def test_default_cost_account_fallback_is_cached(db_session):
    cost_type = CostType(code="travel", name="Travel")
    db_session.add(cost_type)
    db_session.commit()
    cache = {}
    first = job_costing._default_cost_account(db_session, cost_type, cache)
    second = job_costing._default_cost_account(db_session, cost_type, cache)
    assert first is second
    assert first.name == "Job Costs"


def test_job_cost_filters_and_service_errors(
    authed_client, seed_accounts, seed_customer, monkeypatch
):
    job = authed_client.post(
        "/api/jobs", json={"customer_id": seed_customer.id, "name": "Filtered"}
    ).json()
    authed_client.post("/api/cost-types/setup-offsets")
    payload = {
        "date": "2026-09-08",
        "job_id": job["id"],
        "lines": [{"cost_type": "material", "amount": 10}],
    }
    created = authed_client.post("/api/job-costs", json=payload)
    assert created.status_code == 201, created.text
    filtered = authed_client.get(
        f"/api/job-costs?job_id={job['id']}&status=posted&start_date=2026-09-01&end_date=2026-09-30"
    )
    assert filtered.status_code == 200
    assert [row["id"] for row in filtered.json()] == [created.json()["id"]]
    monkeypatch.setattr(
        job_costing,
        "post_job_cost",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("synthetic post")),
    )
    assert authed_client.post("/api/job-costs", json=payload).status_code == 422
    monkeypatch.setattr(
        job_costing,
        "allocate_cost",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("synthetic allocation")
        ),
    )
    allocation = authed_client.post(
        "/api/job-costs/allocate",
        json={
            "date": "2026-09-08",
            "amount": 10,
            "method": "equal",
            "targets": [{"job_id": job["id"], "weight": 1}],
        },
    )
    assert allocation.status_code == 422


def test_equipment_with_posted_cost_cannot_be_deleted(
    authed_client, seed_accounts, seed_customer
):
    job = authed_client.post(
        "/api/jobs", json={"customer_id": seed_customer.id, "name": "Equipment cost"}
    ).json()
    authed_client.post("/api/cost-types/setup-offsets")
    equipment = authed_client.post(
        "/api/equipment", json={"name": "Used equipment", "hourly_rate": 25}
    )
    assert equipment.status_code == 201, equipment.text
    posted = authed_client.post(
        "/api/job-costs",
        json={
            "date": "2026-09-08",
            "job_id": job["id"],
            "lines": [
                {
                    "equipment_id": equipment.json()["id"],
                    "cost_type": "equipment",
                    "amount": 25,
                }
            ],
        },
    )
    assert posted.status_code == 201, posted.text
    response = authed_client.delete(f"/api/equipment/{equipment.json()['id']}")
    assert response.status_code == 400
