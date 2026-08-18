"""Tests for the Workers' Comp SPA page and its backend contracts."""

import re

from fastapi.testclient import TestClient

from app.main import app

_raw = TestClient(app)


def test_page_registered_in_app_routes():
    resp = _raw.get("/static/js/app.js")
    assert "'/payroll/workers-comp'" in resp.text
    assert "'payroll-workers-comp'" in resp.text


def test_navigate_target_resolves():
    app_js = _raw.get("/static/js/app.js").text
    wc_js = _raw.get("/static/js/workers_comp.js").text
    routes = set(re.findall(r"'(/[\w/\-]+)'\s*:", app_js))
    navigates = re.findall(r"App\.navigate\(['\"]#(/[^'\"]+)", wc_js)
    for target in navigates:
        assert target in routes, f"navigate target {target} not in App.routes"


def test_create_and_list_rates(client):
    resp = client.post(
        "/api/workers-comp/rates",
        json={
            "state": "wa",
            "class_code": "8810",
            "description": "Clerical office",
            "rate_per_100": 0.25,
        },
    )
    assert resp.status_code == 201
    rate = resp.json()
    for key in (
        "id",
        "class_code",
        "state",
        "description",
        "rate_per_100",
        "is_active",
    ):
        assert key in rate, f"missing key {key}"
    assert rate["state"] == "WA"
    assert rate["is_active"] is True

    rows = client.get("/api/workers-comp/rates").json()
    assert len(rows) >= 1


def test_new_rate_supersedes_old(client):
    first = client.post(
        "/api/workers-comp/rates",
        json={"state": "WA", "class_code": "5537", "rate_per_100": 4.10},
    ).json()
    client.post(
        "/api/workers-comp/rates",
        json={"state": "WA", "class_code": "5537", "rate_per_100": 4.35},
    )
    rows = client.get("/api/workers-comp/rates").json()
    old = [r for r in rows if r["id"] == first["id"]]
    assert old[0]["is_active"] is False
    active = [r for r in rows if r["class_code"] == "5537" and r["is_active"]]
    assert len(active) == 1
    assert active[0]["rate_per_100"] == 4.35


def test_negative_rate_is_400(client):
    resp = client.post(
        "/api/workers-comp/rates",
        json={"state": "WA", "class_code": "8810", "rate_per_100": -1},
    )
    assert resp.status_code == 400


def test_premium_report_shape(client):
    resp = client.get("/api/workers-comp/premium-report?year=2026")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("year", "rows", "total_premium", "classes_missing_rates"):
        assert key in data, f"missing key {key}"


def test_script_tag_in_index():
    resp = _raw.get("/")
    assert "workers_comp.js" in resp.text


def test_nav_entry_in_index():
    resp = _raw.get("/")
    assert "payroll-workers-comp" in resp.text
    assert "Workers Comp" in resp.text
