"""Employee portal time-entry ownership and workflow coverage."""

from datetime import date
from decimal import Decimal

from app.models.time_entries import TimeEntry, TimeEntryStatus


def _employee(client, first_name: str) -> dict:
    response = client.post(
        "/api/employees",
        json={
            "first_name": first_name,
            "last_name": "Portal",
            "pay_type": "hourly",
            "pay_rate": 25,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "WA",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _claim(client, employee_id: int) -> str:
    token = client.get(f"/api/employees/{employee_id}/portal-token").json()[
        "portal_token"
    ]
    response = client.get(f"/portal/{token}", follow_redirects=False)
    assert response.status_code == 303
    return token


def test_portal_lists_only_owned_entries_and_submits_editable_one(client, db_session):
    employee = _employee(client, "Employee")
    other = _employee(client, "Other")
    owned = TimeEntry(
        employee_id=employee["id"],
        date=date(2026, 9, 1),
        hours_regular=Decimal("8"),
        notes="Owned entry",
        status=TimeEntryStatus.DRAFT,
    )
    approved = TimeEntry(
        employee_id=employee["id"],
        date=date(2026, 9, 2),
        hours_regular=Decimal("7"),
        notes="Already approved",
        status=TimeEntryStatus.APPROVED,
    )
    foreign = TimeEntry(
        employee_id=other["id"],
        date=date(2026, 9, 3),
        hours_regular=Decimal("6"),
        notes="Other employee secret",
        status=TimeEntryStatus.DRAFT,
    )
    db_session.add_all([owned, approved, foreign])
    db_session.commit()

    token = _claim(client, employee["id"])
    page = client.get("/portal/time")
    assert page.status_code == 200
    assert "Owned entry" in page.text
    assert "Already approved" in page.text
    assert "Other employee secret" not in page.text
    assert page.text.count(">Submit</button>") == 1

    legacy = client.get(f"/portal/{token}/time", follow_redirects=False)
    assert legacy.status_code == 303
    assert legacy.headers["location"] == "/portal/time"

    submitted = client.post(f"/portal/time/{owned.id}/submit", follow_redirects=False)
    assert submitted.status_code == 303
    assert submitted.headers["location"] == "/portal/time?submitted=1"
    db_session.refresh(owned)
    assert owned.status == TimeEntryStatus.SUBMITTED

    assert client.post(f"/portal/time/{owned.id}/submit").status_code == 400
    assert client.post(f"/portal/time/{approved.id}/submit").status_code == 400
    assert client.post(f"/portal/time/{foreign.id}/submit").status_code == 404


def test_time_entry_status_cannot_be_bypassed_or_downgraded(client):
    employee = _employee(client, "Workflow")
    created = client.post(
        "/api/time-entries",
        json={
            "employee_id": employee["id"],
            "date": "2026-09-04",
            "hours_regular": 8,
        },
    ).json()
    entry_id = created["id"]

    bypass = client.put(f"/api/time-entries/{entry_id}", json={"status": "approved"})
    assert bypass.status_code == 400
    assert client.post(f"/api/time-entries/{entry_id}/submit").status_code == 200
    assert client.post(f"/api/time-entries/{entry_id}/submit").status_code == 400
    assert (
        client.put(
            f"/api/time-entries/{entry_id}", json={"hours_regular": 12}
        ).status_code
        == 400
    )
    assert client.delete(f"/api/time-entries/{entry_id}").status_code == 400
    approved = client.post(
        f"/api/time-entries/{entry_id}/approve", json={"approved_by": "Manager"}
    )
    assert approved.status_code == 200
    assert (
        client.post(
            f"/api/time-entries/{entry_id}/approve",
            json={"approved_by": "Manager"},
        ).status_code
        == 400
    )
    assert client.post(f"/api/time-entries/{entry_id}/submit").status_code == 400


def test_time_entry_daily_hours_are_bounded(client):
    employee = _employee(client, "Hours")
    base = {"employee_id": employee["id"], "date": "2026-09-05"}
    for hours in (0, -1, 25):
        response = client.post(
            "/api/time-entries", json={**base, "hours_regular": hours}
        )
        assert response.status_code == 422

    created = client.post(
        "/api/time-entries",
        json={**base, "hours_regular": 16, "hours_overtime": 8},
    )
    assert created.status_code == 201
    too_many = client.put(
        f"/api/time-entries/{created.json()['id']}",
        json={"hours_doubletime": 1},
    )
    assert too_many.status_code == 400

    for field in ("date", "hours_regular", "hours_overtime", "hours_doubletime"):
        response = client.put(
            f"/api/time-entries/{created.json()['id']}",
            json={field: None},
        )
        assert response.status_code == 422


def test_documents_page_wins_over_portal_token_catchall(client):
    employee = _employee(client, "Documents")
    _claim(client, employee["id"])
    response = client.get("/portal/documents")
    assert response.status_code == 200
    assert "Documents to Sign" in response.text
    assert "Documents Portal" in response.text
