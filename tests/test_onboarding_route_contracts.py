"""Onboarding checklist CRUD, lifecycle, and reporting boundaries."""

from decimal import Decimal

from app.models.payroll import Employee


def _employee(client):
    response = client.post(
        "/api/employees",
        json={
            "first_name": "New",
            "last_name": "Hire",
            "hire_date": "2026-09-01",
            "work_state": "WA",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_onboarding_missing_employee_and_first_access_seed(client, db_session):
    assert client.get("/api/onboarding/999999").status_code == 404
    assert client.post("/api/onboarding/999999/seed").status_code == 404

    employee = Employee(
        first_name="Direct",
        last_name="Seed",
        pay_type="hourly",
        pay_rate=Decimal("20"),
        pay_frequency="biweekly",
        filing_status="single",
        is_active=True,
    )
    db_session.add(employee)
    db_session.commit()
    checklist = client.get(f"/api/onboarding/{employee.id}")
    assert checklist.status_code == 200
    assert checklist.json()["total"] == 8
    assert client.post(f"/api/onboarding/{employee.id}/seed").status_code == 200


def test_onboarding_custom_task_update_and_complete(client):
    employee = _employee(client)
    assert (
        client.post(
            "/api/onboarding/tasks",
            json={"employee_id": 999999, "task_type": "w4"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/onboarding/tasks",
            json={"employee_id": employee["id"], "task_type": "invalid"},
        ).status_code
        == 400
    )
    created = client.post(
        "/api/onboarding/tasks",
        json={
            "employee_id": employee["id"],
            "task_type": "policy_acknowledgment",
            "notes": "Initial",
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    endpoint = f"/api/onboarding/tasks/{task_id}"

    assert client.put("/api/onboarding/tasks/999999", json={}).status_code == 404
    assert client.put(endpoint, json={"status": "invalid"}).status_code == 400
    complete = client.put(
        endpoint,
        json={
            "status": "complete",
            "signed": True,
            "notes": "Done",
            "completed_by": "HR",
            "document_id": None,
        },
    )
    assert complete.status_code == 200
    assert complete.json()["completed_at"] is not None
    assert complete.json()["signed_at"] is not None
    reopened = client.put(endpoint, json={"status": "in_progress", "signed": False})
    assert reopened.json()["completed_at"] is None
    assert reopened.json()["signed_at"] is None
    finished = client.post(f"{endpoint}/complete?completed_by=Manager")
    assert finished.status_code == 200
    assert client.post(f"{endpoint}/complete").status_code == 200
    assert client.post("/api/onboarding/tasks/999999/complete").status_code == 404


def test_new_hire_reports_translate_missing_employee(client):
    assert client.get("/api/onboarding/999999/new-hire-report").status_code == 404
    assert client.get("/api/onboarding/999999/new-hire-report/pdf").status_code == 404
