"""Tests for the Contractor Pay Runs SPA page and its backend contracts."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

JS = Path(__file__).resolve().parents[1] / "app" / "static" / "js"

_raw = TestClient(app)


def _seed_accounts_and_vendor(client):
    """Seed a vendor and the two accounts the JE needs."""
    v = client.post("/api/vendors", json={"name": "Acme Consulting"})
    assert v.status_code == 201, v.text
    return v.json()["id"]


def test_page_registered_in_app_routes():
    resp = _raw.get("/static/js/app.js")
    assert "'/payroll/contractors'" in resp.text
    assert "'payroll-contractors'" in resp.text


def test_navigate_target_resolves():
    app_js = _raw.get("/static/js/app.js").text
    cr_js = _raw.get("/static/js/contractor_runs.js").text
    routes = set(re.findall(r"'(/[\w/\-]+)'\s*:", app_js))
    navigates = re.findall(r"App\.navigate\(['\"]#(/[^'\"]+)", cr_js)
    for target in navigates:
        assert target in routes, f"navigate target {target} not in App.routes"


def test_run_list_response_shape(client):
    vid = _seed_accounts_and_vendor(client)
    client.post(
        "/api/contractor-runs",
        json={
            "pay_date": "2026-08-15",
            "memo": "Aug contractors",
            "payments": [
                {"vendor_id": vid, "amount": 2500.0, "description": "Dev work"}
            ],
        },
    )
    resp = client.get("/api/contractor-runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 1
    r = runs[0]
    for key in (
        "id",
        "pay_date",
        "memo",
        "status",
        "total_amount",
        "transaction_id",
        "payments",
    ):
        assert key in r, f"missing {key}"
    assert r["status"] == "draft"
    assert r["payments"][0]["vendor_name"] == "Acme Consulting"


def test_run_detail_response_shape(client):
    vid = _seed_accounts_and_vendor(client)
    created = client.post(
        "/api/contractor-runs",
        json={
            "pay_date": "2026-08-15",
            "payments": [{"vendor_id": vid, "amount": 2500.0}],
        },
    ).json()
    resp = client.get(f"/api/contractor-runs/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["payments"][0]["amount"] == 2500.0


def test_create_run_requires_payments(client):
    resp = client.post(
        "/api/contractor-runs",
        json={
            "pay_date": "2026-09-01",
            "payments": [],
        },
    )
    assert resp.status_code == 400


def test_create_and_process_run(client):
    vid = _seed_accounts_and_vendor(client)
    from app.database import get_db

    db = next(get_db())
    from app.models.accounts import Account

    for num, name, typ in [
        ("1000", "Cash", "asset"),
        ("6130", "Contractor Expense", "expense"),
    ]:
        if not db.query(Account).filter(Account.account_number == num).first():
            db.add(Account(account_number=num, name=name, account_type=typ, balance=0))
    db.commit()

    created = client.post(
        "/api/contractor-runs",
        json={
            "pay_date": "2026-09-01",
            "payments": [{"vendor_id": vid, "amount": 1000.0}],
        },
    ).json()
    run_id = created["id"]

    resp = client.post(f"/api/contractor-runs/{run_id}/process")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "processed"
    assert body["transaction_id"] is not None

    resp = client.get(f"/api/contractor-runs/{run_id}")
    assert resp.json()["status"] == "processed"


def test_process_already_processed_is_400(client):
    vid = _seed_accounts_and_vendor(client)
    from app.database import get_db

    db = next(get_db())
    from app.models.accounts import Account

    for num, name, typ in [
        ("1000", "Cash", "asset"),
        ("6130", "Contractor Expense", "expense"),
    ]:
        if not db.query(Account).filter(Account.account_number == num).first():
            db.add(Account(account_number=num, name=name, account_type=typ, balance=0))
    db.commit()

    created = client.post(
        "/api/contractor-runs",
        json={
            "pay_date": "2026-09-01",
            "payments": [{"vendor_id": vid, "amount": 500.0}],
        },
    ).json()
    client.post(f"/api/contractor-runs/{created['id']}/process")
    resp = client.post(f"/api/contractor-runs/{created['id']}/process")
    assert resp.status_code == 400


def test_nacha_requires_processed_run(client):
    vid = _seed_accounts_and_vendor(client)
    created = client.post(
        "/api/contractor-runs",
        json={
            "pay_date": "2026-09-01",
            "payments": [{"vendor_id": vid, "amount": 500.0}],
        },
    ).json()
    resp = client.post(
        f"/api/contractor-runs/{created['id']}/nacha",
        json={
            "immediate_destination": "021000021",
            "immediate_origin": "123456789",
            "originating_dfi_id": "02100002",
        },
    )
    assert resp.status_code == 400


def test_script_tag_in_index():
    resp = _raw.get("/")
    assert "contractor_runs.js" in resp.text


def test_nav_entry_in_index():
    resp = _raw.get("/")
    assert "payroll-contractors" in resp.text
    assert "Contractor Runs" in resp.text


def test_status_badges_cover_all_states():
    js = (JS / "contractor_runs.js").read_text()
    assert "processed" in js
    assert "void" in js
    assert "draft" in js
