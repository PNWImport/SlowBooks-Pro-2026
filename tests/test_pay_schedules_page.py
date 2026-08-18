"""Tests for the Pay Schedules SPA page and its backend contracts."""

import re

from fastapi.testclient import TestClient

from app.main import app

_raw = TestClient(app)


def test_page_registered_in_app_routes():
    resp = _raw.get("/static/js/app.js")
    assert "'/payroll/schedules'" in resp.text
    assert "'payroll-schedules'" in resp.text


def test_navigate_target_resolves():
    app_js = _raw.get("/static/js/app.js").text
    ps_js = _raw.get("/static/js/pay_schedules.js").text
    routes = set(re.findall(r"'(/[\w/\-]+)'\s*:", app_js))
    navigates = re.findall(r"App\.navigate\(['\"]#(/[^'\"]+)", ps_js)
    for target in navigates:
        assert target in routes, f"navigate target {target} not in App.routes"


def test_schedule_list_empty(client):
    resp = client.get("/api/pay-schedules")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_schedule(client):
    resp = client.post(
        "/api/pay-schedules",
        json={
            "name": "Biweekly Friday",
            "frequency": "biweekly",
            "anchor_pay_date": "2026-08-14",
            "submission_lead_days": 3,
            "weekend_shift": "previous_business_day",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    for key in (
        "id",
        "name",
        "frequency",
        "anchor_pay_date",
        "submission_lead_days",
        "weekend_shift",
        "is_active",
    ):
        assert key in data, f"missing key {key}"
    assert data["name"] == "Biweekly Friday"
    assert data["frequency"] == "biweekly"
    assert data["is_active"] is True


def test_create_duplicate_name_is_400(client):
    client.post(
        "/api/pay-schedules",
        json={
            "name": "Monthly",
            "frequency": "monthly",
            "anchor_pay_date": "2026-08-01",
        },
    )
    resp = client.post(
        "/api/pay-schedules",
        json={
            "name": "Monthly",
            "frequency": "monthly",
            "anchor_pay_date": "2026-09-01",
        },
    )
    assert resp.status_code == 400


def test_update_schedule(client):
    created = client.post(
        "/api/pay-schedules",
        json={
            "name": "Weekly Test",
            "frequency": "weekly",
            "anchor_pay_date": "2026-08-07",
        },
    ).json()
    resp = client.put(
        f"/api/pay-schedules/{created['id']}",
        json={"name": "Weekly Updated", "is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Weekly Updated"
    assert resp.json()["is_active"] is False


def test_upcoming_dates(client):
    created = client.post(
        "/api/pay-schedules",
        json={
            "name": "Biweekly Preview",
            "frequency": "biweekly",
            "anchor_pay_date": "2026-08-14",
            "submission_lead_days": 2,
            "weekend_shift": "previous_business_day",
        },
    ).json()
    resp = client.get(f"/api/pay-schedules/{created['id']}/upcoming?count=6")
    assert resp.status_code == 200
    data = resp.json()
    assert "schedule" in data
    assert "dates" in data
    assert len(data["dates"]) == 6
    for d in data["dates"]:
        assert "pay_date" in d
        assert "submission_cutoff" in d


def test_assign_employee(client):
    emp = client.post(
        "/api/employees",
        json={
            "first_name": "Alice",
            "last_name": "Smith",
            "pay_type": "salary",
            "pay_rate": 60000,
            "pay_frequency": "monthly",
            "filing_status": "single",
            "work_state": "WA",
        },
    )
    assert emp.status_code == 201
    emp_id = emp.json()["id"]

    sched = client.post(
        "/api/pay-schedules",
        json={
            "name": "Assign Test",
            "frequency": "biweekly",
            "anchor_pay_date": "2026-08-14",
        },
    ).json()

    resp = client.post(f"/api/pay-schedules/{sched['id']}/assign/{emp_id}")
    assert resp.status_code == 200
    assert resp.json()["employee_id"] == emp_id
    assert resp.json()["pay_schedule_id"] == sched["id"]


def test_invalid_frequency_is_400(client):
    resp = client.post(
        "/api/pay-schedules",
        json={
            "name": "Bad Freq",
            "frequency": "annually",
            "anchor_pay_date": "2026-08-01",
        },
    )
    assert resp.status_code == 400


def test_script_tag_in_index():
    resp = _raw.get("/")
    assert "pay_schedules.js" in resp.text


def test_nav_entry_in_index():
    resp = _raw.get("/")
    assert "payroll-schedules" in resp.text
    assert "Pay Schedules" in resp.text
