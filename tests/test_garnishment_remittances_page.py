"""Tests for the Garnishment Remittance SPA page and its backend contracts."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

_raw = TestClient(app)


@pytest.fixture()
def _seed(client, db_session):
    """Seed an employee, garnishment order, pay run, and remittance row."""
    from app.models.payroll import PayRun
    from app.models.deductions import (
        GarnishmentOrder,
        GarnishmentType,
        GarnishmentMethod,
        GarnishmentRemittance,
    )

    emp = client.post(
        "/api/employees",
        json={
            "first_name": "Jane",
            "last_name": "Doe",
            "pay_type": "salary",
            "pay_rate": 50000,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "WA",
        },
    )
    assert emp.status_code == 201, emp.text
    emp_id = emp.json()["id"]

    order = GarnishmentOrder(
        employee_id=emp_id,
        case_number="CS-2026-001",
        garnishment_type=GarnishmentType.CHILD_SUPPORT,
        calc_method=GarnishmentMethod.FIXED,
        amount=Decimal("500.00"),
        agency_name="State CSE",
        priority=1,
        is_active=True,
    )
    db_session.add(order)
    db_session.flush()

    run = PayRun(
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 15),
        pay_date=date(2026, 8, 15),
    )
    db_session.add(run)
    db_session.flush()

    rem = GarnishmentRemittance(
        order_id=order.id,
        pay_run_id=run.id,
        employee_id=emp_id,
        amount=Decimal("500.00"),
        withheld_date=date(2026, 8, 15),
    )
    db_session.add(rem)
    db_session.commit()
    return {"remittance_id": rem.id, "order_id": order.id, "employee_id": emp_id}


def test_page_registered_in_app_routes():
    resp = _raw.get("/static/js/app.js")
    assert "'/payroll/remittances'" in resp.text
    assert "'payroll-remittances'" in resp.text


def test_navigate_target_resolves():
    app_js = _raw.get("/static/js/app.js").text
    gr_js = _raw.get("/static/js/garnishment_remittances.js").text
    routes = set(re.findall(r"'(/[\w/\-]+)'\s*:", app_js))
    navigates = re.findall(r"App\.navigate\(['\"]#(/[^'\"]+)", gr_js)
    for target in navigates:
        assert target in routes, f"navigate target {target} not in App.routes"


def test_remittance_list_pending(client, _seed):
    resp = client.get("/api/deductions/garnishments/remittances?status=pending")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_pending"] == 500.0
    assert len(data["rows"]) >= 1
    r = data["rows"][0]
    for key in (
        "id",
        "order_id",
        "pay_run_id",
        "employee_id",
        "employee_name",
        "garnishment_type",
        "agency_name",
        "agency_missing",
        "case_number",
        "amount",
        "withheld_date",
        "remitted_at",
        "remit_payment_reference",
    ):
        assert key in r, f"missing key {key}"
    assert r["remitted_at"] is None
    assert r["agency_missing"] is False


def test_remittance_list_all(client, _seed):
    resp = client.get("/api/deductions/garnishments/remittances?status=all")
    assert resp.status_code == 200
    assert len(resp.json()["rows"]) >= 1


def test_mark_remitted(client, _seed):
    data = _seed
    resp = client.post(
        f"/api/deductions/garnishments/remittances/{data['remittance_id']}/mark-remitted",
        json={"payment_reference": "CHK #9876"},
    )
    assert resp.status_code == 200
    assert resp.json()["remitted_at"] is not None

    resp = client.get("/api/deductions/garnishments/remittances?status=pending")
    assert resp.json()["total_pending"] == 0.0


def test_mark_remitted_twice_is_400(client, _seed):
    data = _seed
    client.post(
        f"/api/deductions/garnishments/remittances/{data['remittance_id']}/mark-remitted",
        json={"payment_reference": "CHK #9876"},
    )
    resp = client.post(
        f"/api/deductions/garnishments/remittances/{data['remittance_id']}/mark-remitted",
        json={"payment_reference": "CHK #9877"},
    )
    assert resp.status_code == 400


def test_agency_missing_flag(client, db_session):
    from app.models.payroll import PayRun
    from app.models.deductions import (
        GarnishmentOrder,
        GarnishmentType,
        GarnishmentMethod,
        GarnishmentRemittance,
    )

    emp = client.post(
        "/api/employees",
        json={
            "first_name": "Bob",
            "last_name": "Smith",
            "pay_type": "salary",
            "pay_rate": 40000,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "WA",
        },
    ).json()

    order = GarnishmentOrder(
        employee_id=emp["id"],
        case_number="TL-2026-002",
        garnishment_type=GarnishmentType.STATE_TAX_LEVY,
        calc_method=GarnishmentMethod.FIXED,
        amount=Decimal("200.00"),
        priority=2,
        is_active=True,
    )
    db_session.add(order)
    db_session.flush()

    run = PayRun(
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 15),
        pay_date=date(2026, 8, 15),
    )
    db_session.add(run)
    db_session.flush()

    db_session.add(
        GarnishmentRemittance(
            order_id=order.id,
            pay_run_id=run.id,
            employee_id=emp["id"],
            amount=Decimal("200.00"),
            withheld_date=date(2026, 8, 15),
        )
    )
    db_session.commit()

    resp = client.get("/api/deductions/garnishments/remittances?status=pending")
    rows = resp.json()["rows"]
    missing_row = [r for r in rows if r["case_number"] == "TL-2026-002"]
    assert len(missing_row) == 1
    assert missing_row[0]["agency_missing"] is True


def test_invalid_status_is_400(client):
    resp = client.get("/api/deductions/garnishments/remittances?status=invalid")
    assert resp.status_code == 400


def test_script_tag_in_index():
    resp = _raw.get("/")
    assert "garnishment_remittances.js" in resp.text


def test_nav_entry_in_index():
    resp = _raw.get("/")
    assert "payroll-remittances" in resp.text
    assert "Remittances" in resp.text
