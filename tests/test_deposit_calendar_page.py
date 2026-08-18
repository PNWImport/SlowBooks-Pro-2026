"""Tests for the Tax Deposit Calendar SPA page and its backend contracts."""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

_raw = TestClient(app)


def test_page_registered_in_app_routes():
    resp = _raw.get("/static/js/app.js")
    assert "'/payroll/deposit-calendar'" in resp.text
    assert "'payroll-deposit-calendar'" in resp.text


def test_navigate_target_resolves():
    app_js = _raw.get("/static/js/app.js").text
    dc_js = _raw.get("/static/js/deposit_calendar.js").text
    routes = set(re.findall(r"'(/[\w/\-]+)'\s*:", app_js))
    navigates = re.findall(r"App\.navigate\(['\"]#(/[^'\"]+)", dc_js)
    for target in navigates:
        assert target in routes, f"navigate target {target} not in App.routes"


def test_deposit_schedule_shape(client):
    resp = client.get("/api/tax-forms/deposit-schedule?year=2026")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("year", "lookback_start", "lookback_end", "lookback_quarters",
                "lookback_total", "threshold", "schedule", "note"):
        assert key in data, f"missing key {key}"
    assert data["schedule"] in ("monthly", "semiweekly")
    assert len(data["lookback_quarters"]) == 4


def test_liability_calendar_shape(client):
    resp = client.get("/api/tax-forms/liability-calendar?year=2026")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("year", "schedule", "warnings", "entries"):
        assert key in data, f"missing key {key}"
    # Form 940 + the four 941 filings are always present.
    rules = {e["rule"] for e in data["entries"]}
    assert "return_940" in rules
    assert "return_941" in rules
    for e in data["entries"]:
        for key in ("period", "description", "amount", "due_date", "rule"):
            assert key in e, f"missing entry key {key}"


def test_script_tag_in_index():
    resp = _raw.get("/")
    assert "deposit_calendar.js" in resp.text


def test_nav_entry_in_index():
    resp = _raw.get("/")
    assert "payroll-deposit-calendar" in resp.text
    assert "Deposit Calendar" in resp.text
