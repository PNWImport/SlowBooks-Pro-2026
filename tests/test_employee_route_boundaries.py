"""Employee route error handling and document/direct-deposit boundaries."""


from app.models.payroll import Employee
from app.routes import employees


def _employee(client, **extra):
    body = {"first_name": "Route", "last_name": "Boundary"}
    body.update(extra)
    response = client.post("/api/employees", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_employee_crud_private_view_and_missing_subresources(
    client, db_session, monkeypatch
):
    employee = _employee(client, pay_rate=42)
    employee_id = employee["id"]
    assert len(client.get("/api/employees?active_only=true").json()) == 1
    assert client.get("/api/employees/999999").status_code == 404
    assert (
        client.put("/api/employees/999999", json={"first_name": "x"}).status_code == 404
    )
    assert (
        client.put(
            f"/api/employees/{employee_id}", json={"is_active": False}
        ).status_code
        == 200
    )

    row = db_session.query(Employee).filter(Employee.id == employee_id).first()
    monkeypatch.setattr(employees, "is_admin", lambda request: False)
    assert employees._employee_view(row, object())["pay_rate"] == 0

    endpoints = [
        "portal-token",
        "everify",
        "portal-access",
        "ytd",
        "bank-accounts",
        "documents",
    ]
    for suffix in endpoints:
        assert client.get(f"/api/employees/999999/{suffix}").status_code == 404
    assert client.post("/api/employees/999999/portal-token").status_code == 404
    assert client.put("/api/employees/999999/everify", json={}).status_code == 404


def test_employee_bank_account_validation_and_removal(client):
    employee_id = _employee(client)["id"]
    endpoint = f"/api/employees/{employee_id}/bank-accounts"
    valid = {
        "routing_number": "021000021",
        "account_number": "123456789",
    }
    assert (
        client.post("/api/employees/999999/bank-accounts", json=valid).status_code
        == 404
    )
    assert (
        client.post(endpoint, json={**valid, "account_kind": "invalid"}).status_code
        == 400
    )
    assert (
        client.post(endpoint, json={**valid, "deposit_type": "invalid"}).status_code
        == 400
    )
    assert (
        client.post(endpoint, json={**valid, "account_number": "abc"}).status_code
        == 400
    )

    created = client.post(endpoint, json=valid)
    assert created.status_code == 201, created.text
    assert len(client.get(endpoint).json()) == 1
    account_id = created.json()["id"]
    assert client.delete(f"{endpoint}/{account_id}").status_code == 200
    assert client.delete(f"{endpoint}/{account_id}").status_code == 404


def test_employee_document_boundaries(client, db_session, monkeypatch):
    missing_endpoint = "/api/employees/999999/documents"
    assert (
        client.post(
            missing_endpoint,
            files={"file": ("offer.pdf", b"pdf", "application/pdf")},
        ).status_code
        == 404
    )

    employee_id = _employee(client)["id"]
    endpoint = f"/api/employees/{employee_id}/documents"
    assert (
        client.post(
            endpoint,
            files={"file": ("offer.pdf", b"pdf", "application/octet-stream")},
        ).status_code
        == 400
    )

    async def oversized(*args, **kwargs):
        return b"x" * (50 * 1024 * 1024 + 1)

    monkeypatch.setattr(employees, "read_limited", oversized)
    assert (
        client.post(
            endpoint,
            files={"file": ("large.pdf", b"x", "application/pdf")},
        ).status_code
        == 400
    )
    monkeypatch.undo()

    uploaded = client.post(
        endpoint,
        files={"file": ("offer.pdf", b"pdf", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]
    assert len(client.get(endpoint).json()) == 1

    from app.models.attachments import Attachment

    document = db_session.query(Attachment).filter(Attachment.id == document_id).first()
    # Documents live in the database now: a copy flagged missing (an upgrade
    # that could not find the original file) is named, not served.
    document.stored_file.missing = True
    db_session.commit()
    assert client.get(f"{endpoint}/{document_id}").status_code == 404
    assert client.delete(f"{endpoint}/{document_id}").status_code == 200
    assert client.get(f"{endpoint}/{document_id}").status_code == 404
    assert client.delete(f"{endpoint}/{document_id}").status_code == 404


def test_termination_resolves_attached_schedule(client):
    employee_id = _employee(client, work_state="WA")["id"]
    schedule = client.post(
        "/api/pay-schedules",
        json={
            "name": "Termination Calendar",
            "frequency": "biweekly",
            "anchor_pay_date": "2026-01-09",
        },
    )
    assert schedule.status_code == 201, schedule.text
    schedule_id = schedule.json()["id"]
    assert (
        client.post(
            f"/api/pay-schedules/{schedule_id}/assign/{employee_id}"
        ).status_code
        == 200
    )

    terminated = client.post(
        f"/api/employees/{employee_id}/terminate",
        json={
            "termination_date": "2026-06-10",
            "reason": "voluntary",
            "payout_pto": False,
        },
    )
    assert terminated.status_code == 200, terminated.text
    assert terminated.json()["final_paycheck"]["due_date"] is not None
