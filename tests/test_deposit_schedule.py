# ============================================================================
# Deposit-schedule determination + liability-calendar coverage.
# ----------------------------------------------------------------------------
# Pins the Pub 15 mechanics: the lookback window (Jul 1 Y-2 .. Jun 30 Y-1),
# the $50k monthly/semiweekly threshold, monthly due-the-15th (rolled off
# weekends), the semiweekly Wed-Fri->Wednesday / Sat-Tue->Friday mapping,
# the $100k next-day rule, de-minimis quarters, the FUTA $500 floor with
# carryover, and the merged calendar ordering.
# ============================================================================

from datetime import date
from decimal import Decimal

import pytest

from app.services.tax_forms.deposit_schedule import (
    _next_business_day,
    _semiweekly_due,
    determine_deposit_schedule,
    federal_deposit_events,
    futa_deposit_events,
    liability_calendar,
)


def _create_employee(client, **overrides):
    body = {
        "first_name": "Pat",
        "last_name": "Worker",
        "pay_type": "hourly",
        "pay_rate": 25,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _run_payroll(client, emp_id, pay_date, gross=None, hours=80):
    stub = {"employee_id": emp_id, "hours": hours}
    if gross is not None:
        stub = {
            "employee_id": emp_id,
            "gross_override": gross,
            "supplemental": True,
        }
    r = client.post(
        "/api/payroll",
        json={
            "period_start": pay_date,
            "period_end": pay_date,
            "pay_date": pay_date,
            "run_type": "regular" if gross is None else "bonus",
            "stubs": [stub],
        },
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert client.post(f"/api/payroll/{run['id']}/process").status_code == 200
    return run


# --- date helpers -----------------------------------------------------------


def test_next_business_day_rolls_weekends():
    assert _next_business_day(date(2026, 8, 15)) == date(2026, 8, 17)  # Sat -> Mon
    assert _next_business_day(date(2026, 8, 16)) == date(2026, 8, 17)  # Sun -> Mon
    assert _next_business_day(date(2026, 8, 17)) == date(2026, 8, 17)  # Mon stays


@pytest.mark.parametrize(
    "pay_date,due",
    [
        (date(2026, 8, 12), date(2026, 8, 19)),  # Wed -> next Wed
        (date(2026, 8, 14), date(2026, 8, 19)),  # Fri -> next Wed
        (date(2026, 8, 15), date(2026, 8, 21)),  # Sat -> next Fri
        (date(2026, 8, 17), date(2026, 8, 21)),  # Mon -> Fri same week
        (date(2026, 8, 18), date(2026, 8, 21)),  # Tue -> Fri same week
    ],
)
def test_semiweekly_due_mapping(pay_date, due):
    assert _semiweekly_due(pay_date) == due


# --- lookback determination -------------------------------------------------


def test_new_employer_defaults_to_monthly(client, db_session):
    result = determine_deposit_schedule(db_session, 2026)
    assert result["schedule"] == "monthly"
    assert result["lookback_total"] == 0
    assert result["lookback_start"] == "2024-07-01"
    assert result["lookback_end"] == "2025-06-30"
    assert len(result["lookback_quarters"]) == 4
    assert "New employers" in result["note"]


def test_lookback_counts_only_window_quarters(client, db_session, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2024-08-15")  # inside (Q3 2024)
    _run_payroll(client, emp["id"], "2026-02-15")  # outside (current year)
    result = determine_deposit_schedule(db_session, 2026)
    assert result["lookback_total"] > 0
    q3_2024 = [
        q
        for q in result["lookback_quarters"]
        if q["year"] == 2024 and q["quarter"] == 3
    ][0]
    assert q3_2024["form_941_tax"] == result["lookback_total"]


def test_semiweekly_when_lookback_exceeds_50k(client, db_session, seed_accounts):
    emp = _create_employee(client)
    # One enormous bonus run in the lookback window: 941 tax on $200k gross
    # (22% federal supplemental + FICA both sides) is far over $50k.
    _run_payroll(client, emp["id"], "2025-03-14", gross=200000)
    result = determine_deposit_schedule(db_session, 2026)
    assert result["lookback_total"] > 50000
    assert result["schedule"] == "semiweekly"


# --- deposit events ---------------------------------------------------------


def test_monthly_events_due_15th_next_month(client, db_session, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-05-15")
    _run_payroll(client, emp["id"], "2026-05-29")
    result = federal_deposit_events(db_session, 2026)
    assert result["schedule"] == "monthly"
    may = [e for e in result["events"] if e["period"] == "2026-05"]
    assert len(may) == 1
    assert may[0]["due_date"] == "2026-06-15"  # June 15 2026 is a Monday
    assert may[0]["amount"] > 0


def test_monthly_due_date_rolls_off_weekend(client, db_session, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-07-10")
    result = federal_deposit_events(db_session, 2026)
    july = [e for e in result["events"] if e["period"] == "2026-07"][0]
    # Aug 15 2026 is a Saturday -> due Monday Aug 17.
    assert july["due_date"] == "2026-08-17"


def test_december_deposit_due_next_january(client, db_session, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-12-11")
    result = federal_deposit_events(db_session, 2026)
    dec = [e for e in result["events"] if e["period"] == "2026-12"][0]
    assert dec["due_date"] == "2027-01-15"


def test_semiweekly_events_group_by_due_date(client, db_session, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-08-12")  # Wed
    _run_payroll(client, emp["id"], "2026-08-14")  # Fri, same window
    result = federal_deposit_events(db_session, 2026, schedule="semiweekly")
    assert len(result["events"]) == 1
    assert result["events"][0]["due_date"] == "2026-08-19"


def test_100k_next_day_rule(client, db_session, seed_accounts):
    emp = _create_employee(client)
    # $400k gross on one day: 941 tax comfortably over $100k. ($300k is a
    # near miss — 22% supplemental + capped SS + Medicare ≈ $98.5k.)
    _run_payroll(client, emp["id"], "2026-06-10", gross=400000)
    result = federal_deposit_events(db_session, 2026)
    next_day = [e for e in result["events"] if e["rule"] == "next_day"]
    assert len(next_day) == 1
    assert next_day[0]["due_date"] == "2026-06-11"
    assert any("next-day" in w or "$100k" in w for w in result["warnings"])


def test_de_minimis_quarter_warned(client, db_session, seed_accounts):
    emp = _create_employee(client, pay_rate=8)  # tiny quarterly liability
    _run_payroll(client, emp["id"], "2026-02-13", hours=10)
    result = federal_deposit_events(db_session, 2026)
    assert any("de-minimis" in w for w in result["warnings"])


def test_invalid_schedule_rejected(db_session):
    with pytest.raises(ValueError):
        federal_deposit_events(db_session, 2026, schedule="fortnightly")


# --- FUTA -------------------------------------------------------------------


def test_futa_under_500_rides_the_return(client, db_session, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-02-13")
    events = futa_deposit_events(db_session, 2026)
    # One biweekly check yields ~$25 of FUTA — under the $500 floor all year.
    assert len(events) == 1
    assert events[0]["rule"] == "futa_with_return"
    assert events[0]["due_date"] == "2027-02-01"  # Jan 31 2027 is a Sunday


def test_futa_over_500_deposits_quarterly_with_carryover(
    client, db_session, seed_accounts
):
    # FUTA is 0.6% of the first $7,000 per employee = $42 max each. Twelve
    # employees paid in Q1 clear the $500 floor.
    ids = [
        _create_employee(client, first_name=f"E{i}", pay_rate=90)["id"]
        for i in range(12)
    ]
    for emp_id in ids:
        _run_payroll(client, emp_id, "2026-02-13")
    events = futa_deposit_events(db_session, 2026)
    q1 = [e for e in events if e["period"] == "2026-Q1"]
    assert len(q1) == 1
    assert q1[0]["rule"] == "futa_quarterly"
    assert q1[0]["amount"] > 500
    assert q1[0]["due_date"] == "2026-04-30"


# --- the merged calendar ----------------------------------------------------


def test_calendar_merges_and_sorts(client, db_session, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-05-15")
    cal = liability_calendar(db_session, 2026)
    assert cal["schedule"] == "monthly"
    rules = {e["rule"] for e in cal["entries"]}
    assert {"monthly", "return_941", "return_940"} <= rules
    dates = [e["due_date"] for e in cal["entries"]]
    assert dates == sorted(dates)
    # State amounts present (WA has employer-side premiums even with no
    # income tax).
    assert any(e["rule"] == "state_quarterly" for e in cal["entries"])


def test_calendar_endpoints(client, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-05-15")
    r = client.get("/api/tax-forms/deposit-schedule?year=2026")
    assert r.status_code == 200
    assert r.json()["schedule"] in ("monthly", "semiweekly")
    r = client.get("/api/tax-forms/liability-calendar?year=2026")
    assert r.status_code == 200
    body = r.json()
    assert body["year"] == 2026
    assert len(body["entries"]) > 0
