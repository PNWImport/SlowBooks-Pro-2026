"""Tests for the HR Team SPA page (org chart / PTO calendar / reviews)."""

import re

from fastapi.testclient import TestClient

from app.main import app

_raw = TestClient(app)


def _mk_employee(client, first, last, manager_id=None):
    payload = {
        "first_name": first,
        "last_name": last,
        "pay_type": "salary",
        "pay_rate": 50000,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
    }
    resp = client.post("/api/employees", json=payload)
    assert resp.status_code == 201, resp.text
    emp = resp.json()
    if manager_id is not None:
        from app.database import get_db
        from app.models.payroll import Employee

        db = next(get_db())
        e = db.query(Employee).filter(Employee.id == emp["id"]).first()
        e.manager_id = manager_id
        db.commit()
    return emp["id"]


def test_page_registered_in_app_routes():
    resp = _raw.get("/static/js/app.js")
    assert "'/hr/team'" in resp.text
    assert "'hr-team'" in resp.text


def test_navigate_target_resolves():
    app_js = _raw.get("/static/js/app.js").text
    hr_js = _raw.get("/static/js/hr_views.js").text
    routes = set(re.findall(r"'(/[\w/\-]+)'\s*:", app_js))
    navigates = re.findall(r"App\.navigate\(['\"]#(/[^'\"]+)", hr_js)
    for target in navigates:
        assert target in routes, f"navigate target {target} not in App.routes"


def test_org_chart_tree(client):
    boss = _mk_employee(client, "Big", "Boss")
    _mk_employee(client, "Direct", "Report", manager_id=boss)

    resp = client.get("/api/hr/org-chart")
    assert resp.status_code == 200
    data = resp.json()
    assert "tree" in data
    assert "cycle_employee_ids" in data
    boss_node = [n for n in data["tree"] if n["name"] == "Big Boss"]
    assert len(boss_node) == 1
    assert boss_node[0]["reports"][0]["name"] == "Direct Report"


def test_pto_calendar_window(client):
    resp = client.get("/api/hr/pto-calendar?start=2026-08-01&end=2026-08-31")
    assert resp.status_code == 200
    data = resp.json()
    assert data["start"] == "2026-08-01"
    assert "entries" in data


def test_pto_calendar_bad_window_is_400(client):
    resp = client.get("/api/hr/pto-calendar?start=2026-08-31&end=2026-08-01")
    assert resp.status_code == 400


def test_review_lifecycle(client):
    emp = _mk_employee(client, "Review", "Target")

    created = client.post(
        "/api/hr/reviews",
        json={
            "employee_id": emp,
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
            "rating": 4,
            "goals": "Ship the thing",
        },
    )
    assert created.status_code == 201
    review = created.json()
    for key in (
        "id",
        "employee_id",
        "employee_name",
        "reviewer_name",
        "period_start",
        "period_end",
        "status",
        "rating",
        "goals",
        "feedback",
        "employee_comment",
        "submitted_at",
        "acknowledged_at",
    ):
        assert key in review, f"missing key {key}"
    assert review["status"] == "draft"
    rid = review["id"]

    resp = client.put(f"/api/hr/reviews/{rid}", json={"feedback": "Solid half."})
    assert resp.status_code == 200
    assert resp.json()["feedback"] == "Solid half."

    resp = client.post(f"/api/hr/reviews/{rid}/submit")
    assert resp.status_code == 200
    assert resp.json()["status"] == "submitted"

    # Submitted reviews are no longer editable.
    resp = client.put(f"/api/hr/reviews/{rid}", json={"rating": 5})
    assert resp.status_code == 400

    resp = client.post(
        f"/api/hr/reviews/{rid}/acknowledge",
        json={"employee_comment": "Thanks!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "acknowledged"
    assert body["employee_comment"] == "Thanks!"

    # Double acknowledge is a 400.
    resp = client.post(f"/api/hr/reviews/{rid}/acknowledge", json={})
    assert resp.status_code == 400


def test_review_bad_rating_is_400(client):
    emp = _mk_employee(client, "Bad", "Rating")
    resp = client.post(
        "/api/hr/reviews",
        json={
            "employee_id": emp,
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
            "rating": 9,
        },
    )
    assert resp.status_code == 400


def test_review_list_filter_by_employee(client):
    emp = _mk_employee(client, "Filter", "Me")
    other = _mk_employee(client, "Other", "One")
    for e in (emp, other):
        client.post(
            "/api/hr/reviews",
            json={
                "employee_id": e,
                "period_start": "2026-01-01",
                "period_end": "2026-06-30",
            },
        )
    resp = client.get(f"/api/hr/reviews?employee_id={emp}")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["employee_id"] == emp


def test_script_tag_in_index():
    resp = _raw.get("/")
    assert "hr_views.js" in resp.text


def test_nav_entry_in_index():
    resp = _raw.get("/")
    assert "hr-team" in resp.text
    assert "HR Team" in resp.text
