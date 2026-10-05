"""PTO policy, accrual, request, and liability error contracts."""

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.pto import PTOAccrual
from app.routes import pto
from app.schemas.pto import PTOPolicyCreate, PTORequestCreate


def _employee(client):
    response = client.post(
        "/api/employees",
        json={"first_name": "PTO", "last_name": "Worker", "pay_rate": 25},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _policy(client, **extra):
    body = {
        "name": "Vacation",
        "pto_type": "vacation",
        "accrual_method": "per_pay_period",
        "accrual_rate": 4,
    }
    body.update(extra)
    return client.post("/api/pto/policies", json=body)


def _accrual(client, employee_id, policy_id):
    return client.post(
        "/api/pto/accruals",
        json={"employee_id": employee_id, "policy_id": policy_id, "balance": 8},
    )


def test_pto_policy_crud_validation_and_defensive_enums(client, db_session):
    created = _policy(client)
    assert created.status_code == 201, created.text
    policy_id = created.json()["id"]
    assert len(client.get("/api/pto/policies").json()) == 1
    assert client.get(f"/api/pto/policies/{policy_id}").status_code == 200
    assert client.get("/api/pto/policies/999999").status_code == 404
    policy_body = {
        "name": "Vacation",
        "pto_type": "vacation",
        "accrual_method": "per_pay_period",
        "accrual_rate": 4,
    }
    assert client.put("/api/pto/policies/999999", json=policy_body).status_code == 404
    invalid_valuation = {**policy_body, "valuation": "invalid"}
    assert (
        client.put(f"/api/pto/policies/{policy_id}", json=invalid_valuation).status_code
        == 400
    )
    updated = client.put(
        f"/api/pto/policies/{policy_id}",
        json={**policy_body, "name": "Updated Vacation", "valuation": "average_rate"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated Vacation"

    bad = PTOPolicyCreate.model_construct(
        name="Bad",
        pto_type="invalid",
        accrual_method="invalid",
        valuation="current_rate",
    )
    with pytest.raises(HTTPException) as create_error:
        pto.create_policy(bad, db_session)
    assert create_error.value.status_code == 400
    with pytest.raises(HTTPException) as update_error:
        pto.update_policy(policy_id, bad, db_session)
    assert update_error.value.status_code == 400


def test_pto_accrual_create_filter_run_revalue_and_errors(
    client, db_session, monkeypatch
):
    employee_id = _employee(client)
    policy_id = _policy(client).json()["id"]
    assert _accrual(client, 999999, policy_id).status_code == 404
    assert _accrual(client, employee_id, 999999).status_code == 404
    created = _accrual(client, employee_id, policy_id)
    assert created.status_code == 201, created.text
    accrual_id = created.json()["id"]
    assert _accrual(client, employee_id, policy_id).status_code == 400
    assert len(client.get(f"/api/pto/accruals?employee_id={employee_id}").json()) == 1
    assert client.post("/api/pto/accruals/999999/accrue", json={}).status_code == 404
    assert client.post("/api/pto/accruals/999999/revalue", json={}).status_code == 404

    accrued = client.post(
        f"/api/pto/accruals/{accrual_id}/accrue",
        json={"hours_worked": 80, "as_of": "2026-09-08"},
    )
    assert accrued.status_code == 200, accrued.text
    assert (
        client.post(
            f"/api/pto/accruals/{accrual_id}/revalue", json={"as_of": "2026-09-08"}
        ).status_code
        == 200
    )

    def fail(*args, **kwargs):
        raise ValueError("liability accounts missing")

    monkeypatch.setattr(pto.pto_liability, "accrue_dollars", fail)
    assert (
        client.post(f"/api/pto/accruals/{accrual_id}/accrue", json={}).status_code
        == 400
    )
    monkeypatch.setattr(pto.pto_liability, "revalue", fail)
    assert (
        client.post(f"/api/pto/accruals/{accrual_id}/revalue", json={}).status_code
        == 400
    )


def test_pto_accrual_missing_policy_defense(db_session):
    accrual = PTOAccrual(employee_id=1, policy_id=999999, balance=Decimal("0"))

    class Query:
        calls = 0

        def filter(self, *args):
            return self

        def first(self):
            self.calls += 1
            return accrual if self.calls == 1 else None

    class DB:
        def __init__(self):
            self.result = Query()

        def query(self, *args):
            return self.result

    with pytest.raises(HTTPException, match="Policy not found"):
        pto.run_accrual(1, pto.AccrueRequest(), DB())


def test_pto_request_filters_validation_and_decisions(client, db_session):
    employee_id = _employee(client)
    assert client.get("/api/pto/requests?status=invalid").status_code == 400
    assert (
        client.post(
            "/api/pto/requests",
            json={
                "employee_id": 999999,
                "start_date": "2026-09-08",
                "end_date": "2026-09-09",
                "hours": 8,
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/pto/requests",
            json={
                "employee_id": employee_id,
                "start_date": "2026-09-09",
                "end_date": "2026-09-08",
                "hours": 8,
            },
        ).status_code
        == 400
    )

    request = client.post(
        "/api/pto/requests",
        json={
            "employee_id": employee_id,
            "start_date": "2026-09-08",
            "end_date": "2026-09-08",
            "hours": 4,
            "pto_type": "vacation",
        },
    )
    assert request.status_code == 201, request.text
    request_id = request.json()["id"]
    assert (
        len(
            client.get(
                f"/api/pto/requests?employee_id={employee_id}&status=pending"
            ).json()
        )
        == 1
    )
    assert (
        client.post(
            "/api/pto/requests/999999/decision", json={"status": "approved"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/pto/requests/{request_id}/decision", json={"status": "invalid"}
        ).status_code
        == 400
    )
    assert client.post(f"/api/pto/requests/{request_id}/reject").status_code == 200
    assert client.post(f"/api/pto/requests/{request_id}/approve").status_code == 400

    bad_type = PTORequestCreate.model_construct(
        employee_id=employee_id,
        start_date=request.json()["start_date"],
        end_date=request.json()["end_date"],
        hours=1,
        pto_type="invalid",
        notes=None,
    )
    with pytest.raises(HTTPException):
        pto.create_request(bad_type, db_session)


def test_pto_approval_drawdown_liability_and_carryover(client, monkeypatch):
    employee_id = _employee(client)
    policy_id = _policy(client).json()["id"]
    assert _accrual(client, employee_id, policy_id).status_code == 201

    def request_for(day):
        response = client.post(
            "/api/pto/requests",
            json={
                "employee_id": employee_id,
                "start_date": day,
                "end_date": day,
                "hours": 2,
                "pto_type": "vacation",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    monkeypatch.setattr(pto.pto_liability, "relieve_dollars", lambda *args: None)
    approved = client.post(f"/api/pto/requests/{request_for('2026-09-10')}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    def fail(*args):
        raise ValueError("cannot relieve liability")

    monkeypatch.setattr(pto.pto_liability, "relieve_dollars", fail)
    failed = client.post(f"/api/pto/requests/{request_for('2026-09-11')}/approve")
    assert failed.status_code == 400
    assert (
        client.post("/api/pto/accruals/year-end-carryover?target_year=2026").status_code
        == 200
    )
