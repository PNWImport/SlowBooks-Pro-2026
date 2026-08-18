"""Tests for the Work Locations SPA page and its backend contracts."""

import re

from fastapi.testclient import TestClient

from app.main import app

_raw = TestClient(app)


def test_page_registered_in_app_routes():
    resp = _raw.get("/static/js/app.js")
    assert "'/payroll/locations'" in resp.text
    assert "'payroll-locations'" in resp.text


def test_navigate_target_resolves():
    app_js = _raw.get("/static/js/app.js").text
    loc_js = _raw.get("/static/js/locations.js").text
    routes = set(re.findall(r"'(/[\w/\-]+)'\s*:", app_js))
    navigates = re.findall(r"App\.navigate\(['\"]#(/[^'\"]+)", loc_js)
    for target in navigates:
        assert target in routes, f"navigate target {target} not in App.routes"


def test_location_list_empty(client):
    resp = client.get("/api/locations")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_location(client):
    resp = client.post(
        "/api/locations",
        json={
            "name": "Seattle HQ",
            "state": "WA",
            "city": "Seattle",
            "address1": "123 Main St",
            "zip": "98101",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    for key in (
        "id",
        "name",
        "state",
        "city",
        "address1",
        "address2",
        "zip",
        "locality",
        "default_wc_class_code",
        "is_active",
    ):
        assert key in data, f"missing key {key}"
    assert data["name"] == "Seattle HQ"
    assert data["state"] == "WA"
    assert data["is_active"] is True


def test_create_duplicate_name_is_400(client):
    client.post(
        "/api/locations",
        json={"name": "Portland Office", "state": "OR"},
    )
    resp = client.post(
        "/api/locations",
        json={"name": "Portland Office", "state": "OR"},
    )
    assert resp.status_code == 400


def test_create_invalid_state_is_400(client):
    resp = client.post(
        "/api/locations",
        json={"name": "Bad State", "state": "ZZ"},
    )
    assert resp.status_code == 400


def test_update_location(client):
    created = client.post(
        "/api/locations",
        json={"name": "Update Test", "state": "WA"},
    ).json()
    resp = client.put(
        f"/api/locations/{created['id']}",
        json={"city": "Tacoma", "is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["city"] == "Tacoma"
    assert resp.json()["is_active"] is False


def test_assign_employee(client):
    emp = client.post(
        "/api/employees",
        json={
            "first_name": "Bob",
            "last_name": "Jones",
            "pay_type": "hourly",
            "pay_rate": 25,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "WA",
        },
    )
    assert emp.status_code == 201
    emp_id = emp.json()["id"]

    loc = client.post(
        "/api/locations",
        json={"name": "Assign Loc", "state": "WA"},
    ).json()

    resp = client.post(f"/api/locations/{loc['id']}/assign/{emp_id}")
    assert resp.status_code == 200
    assert resp.json()["employee_id"] == emp_id
    assert resp.json()["location_id"] == loc["id"]


def test_location_employees(client):
    emp = client.post(
        "/api/employees",
        json={
            "first_name": "Carol",
            "last_name": "White",
            "pay_type": "salary",
            "pay_rate": 55000,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "WA",
        },
    ).json()
    loc = client.post(
        "/api/locations",
        json={"name": "Roster Loc", "state": "WA"},
    ).json()
    client.post(f"/api/locations/{loc['id']}/assign/{emp['id']}")

    resp = client.get(f"/api/locations/{loc['id']}/employees")
    assert resp.status_code == 200
    employees = resp.json()
    assert len(employees) >= 1
    e = employees[0]
    assert "id" in e
    assert "name" in e
    assert "is_active" in e


def test_location_employees_404(client):
    resp = client.get("/api/locations/99999/employees")
    assert resp.status_code == 404


def test_script_tag_in_index():
    resp = _raw.get("/")
    assert "locations.js" in resp.text


def test_nav_entry_in_index():
    resp = _raw.get("/")
    assert "payroll-locations" in resp.text
    assert "Work Locations" in resp.text
