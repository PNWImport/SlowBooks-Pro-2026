"""Tests for the Payroll Reports SPA page and its backend contracts."""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

_raw = TestClient(app)


def test_page_registered_in_app_routes():
    resp = _raw.get("/static/js/app.js")
    assert "'/payroll/reports'" in resp.text
    assert "'payroll-reports'" in resp.text


def test_navigate_target_resolves():
    app_js = _raw.get("/static/js/app.js").text
    pr_js = _raw.get("/static/js/payroll_reports.js").text
    routes = set(re.findall(r"'(/[\w/\-]+)'\s*:", app_js))
    navigates = re.findall(r"App\.navigate\(['\"]#(/[^'\"]+)", pr_js)
    for target in navigates:
        assert target in routes, f"navigate target {target} not in App.routes"


def test_payroll_journal_shape(client):
    resp = client.get("/api/reports/payroll-journal?start=2026-01-01&end=2026-12-31")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("start", "end", "runs", "totals"):
        assert key in data, f"missing key {key}"
    for key in ("gross", "federal", "state", "ss", "medicare", "net",
                "employer_taxes", "garnishments"):
        assert key in data["totals"], f"missing totals key {key}"


def test_deduction_register_shape(client):
    resp = client.get("/api/reports/deduction-register?year=2026")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("year", "rows", "totals"):
        assert key in data, f"missing key {key}"
    for key in ("pretax_deductions", "posttax_deductions", "garnishments"):
        assert key in data["totals"], f"missing totals key {key}"


def test_contractor_payments_shape(client):
    resp = client.get("/api/reports/contractor-payments?year=2026")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("year", "rows", "total"):
        assert key in data, f"missing key {key}"


def test_contractor_payments_includes_run_path(client):
    v = client.post("/api/vendors", json={"name": "Report Vendor", "is_1099_vendor": True})
    assert v.status_code == 201
    vid = v.json()["id"]

    from app.database import get_db
    from app.models.accounts import Account

    db = next(get_db())
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
            "pay_date": "2026-07-15",
            "payments": [{"vendor_id": vid, "amount": 1200.0}],
        },
    ).json()
    client.post(f"/api/contractor-runs/{created['id']}/process")

    data = client.get("/api/reports/contractor-payments?year=2026").json()
    row = [r for r in data["rows"] if r["vendor_id"] == vid]
    assert len(row) == 1
    assert row[0]["contractor_run_payments"] == 1200.0
    assert row[0]["is_1099_vendor"] is True
    assert data["total"] >= 1200.0


def test_script_tag_in_index():
    resp = _raw.get("/")
    assert "payroll_reports.js" in resp.text


def test_nav_entry_in_index():
    resp = _raw.get("/")
    assert "payroll-reports" in resp.text
    assert "Payroll Reports" in resp.text
