"""Tests for the retro-pay and termination SPA affordances."""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

_raw = TestClient(app)


def _mk_employee(client, first="Term", last="Case", **overrides):
    payload = {
        "first_name": first,
        "last_name": last,
        "pay_type": "hourly",
        "pay_rate": 20,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
        **overrides,
    }
    resp = client.post("/api/employees", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_payroll_js_calls_retro_endpoints():
    js = _raw.get("/static/js/payroll.js").text
    assert "/payroll/retro-pay/preview" in js
    assert "/payroll/retro-pay/apply" in js
    assert "showRetroPayForm" in js


def test_employees_js_calls_terminate_endpoint():
    js = _raw.get("/static/js/employees.js").text
    assert "/terminate" in js
    assert "showTerminateForm" in js


def test_navigate_targets_resolve():
    app_js = _raw.get("/static/js/app.js").text
    routes = set(re.findall(r"'(/[\w/\-]+)'\s*:", app_js))
    for fname in ("payroll.js", "employees.js"):
        js = _raw.get(f"/static/js/{fname}").text
        for target in re.findall(r"App\.navigate\(['\"]#(/[^'\"]+)", js):
            assert target in routes, f"{fname}: navigate target {target} not in App.routes"


def test_retro_preview_shape(client):
    emp = _mk_employee(client, "Retro", "Preview")
    resp = client.post(
        "/api/payroll/retro-pay/preview",
        json={"employee_id": emp, "new_rate": 25, "effective_date": "2026-01-01"},
    )
    assert resp.status_code == 200
    data = resp.json()
    for key in ("employee_id", "current_rate", "new_rate", "effective_date",
                "periods", "retro_pay_due"):
        assert key in data, f"missing key {key}"
    assert data["retro_pay_due"] == 0.0  # no pay history yet


def test_retro_apply_zero_amount_is_400(client):
    emp = _mk_employee(client, "Retro", "Zero")
    resp = client.post(
        "/api/payroll/retro-pay/apply",
        json={"employee_id": emp, "new_rate": 25, "effective_date": "2026-01-01"},
    )
    assert resp.status_code == 400


def test_terminate_response_shape(client):
    emp = _mk_employee(client, "Off", "Boarded")
    resp = client.post(
        f"/api/employees/{emp}/terminate",
        json={"termination_date": "2026-08-18", "reason": "voluntary"},
    )
    assert resp.status_code == 200
    data = resp.json()
    for key in ("employee_id", "termination_date", "reason", "final_paycheck",
                "pto_payout", "pto_payout_staged", "pto_payout_run_id",
                "deductions_deactivated", "portal_token_revoked"):
        assert key in data, f"missing key {key}"
    # Keys the terminate modal renders.
    assert "deadline_description" in data["final_paycheck"]
    assert "due_date" in data["final_paycheck"]
    assert "total_payout" in data["pto_payout"]

    # Employee is now inactive; the row loses its Terminate button.
    emp_row = client.get(f"/api/employees/{emp}").json()
    assert emp_row["is_active"] is False


def test_terminate_twice_is_400(client):
    emp = _mk_employee(client, "Twice", "Term")
    client.post(
        f"/api/employees/{emp}/terminate",
        json={"termination_date": "2026-08-18", "reason": "voluntary"},
    )
    resp = client.post(
        f"/api/employees/{emp}/terminate",
        json={"termination_date": "2026-08-19", "reason": "voluntary"},
    )
    assert resp.status_code == 400


def test_terminate_bad_reason_is_400(client):
    emp = _mk_employee(client, "Bad", "Reason")
    resp = client.post(
        f"/api/employees/{emp}/terminate",
        json={"termination_date": "2026-08-18", "reason": "rage-quit"},
    )
    assert resp.status_code == 400
