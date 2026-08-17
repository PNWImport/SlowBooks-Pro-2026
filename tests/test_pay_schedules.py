# ============================================================================
# Pay-schedule coverage — date math + CRUD + employee attachment.
# ----------------------------------------------------------------------------
# The date math is the risk surface: biweekly stepping from an anchor,
# semi-monthly month-end capping (the 15th/30th pair in February), monthly
# 31st capping, weekend shifting in both directions, and cutoff derivation.
# ============================================================================

from datetime import date

from app.models.pay_schedules import PaySchedule, WeekendShift
from app.models.payroll import PayFrequency
from app.services.pay_schedule_service import upcoming_pay_dates


def _schedule(**overrides):
    defaults = dict(
        name="Test",
        frequency=PayFrequency.BIWEEKLY,
        anchor_pay_date=date(2026, 1, 9),  # a Friday
        submission_lead_days=2,
        weekend_shift=WeekendShift.PREVIOUS_BUSINESS_DAY,
    )
    defaults.update(overrides)
    return PaySchedule(**defaults)


# --- date math --------------------------------------------------------------


def test_biweekly_steps_from_anchor():
    dates = upcoming_pay_dates(_schedule(), date(2026, 6, 1), count=3)
    # Fridays every 14 days from Jan 9: May 29, then Jun 12, Jun 26, Jul 10.
    assert [d["pay_date"] for d in dates] == ["2026-06-12", "2026-06-26", "2026-07-10"]
    assert all(not d["shifted"] for d in dates)


def test_weekly_steps_seven_days():
    s = _schedule(frequency=PayFrequency.WEEKLY)
    dates = upcoming_pay_dates(s, date(2026, 6, 1), count=3)
    assert [d["pay_date"] for d in dates] == ["2026-06-05", "2026-06-12", "2026-06-19"]


def test_start_on_a_pay_date_includes_it():
    dates = upcoming_pay_dates(_schedule(), date(2026, 6, 12), count=1)
    assert dates[0]["pay_date"] == "2026-06-12"


def test_semi_monthly_pairs_and_february_cap():
    s = _schedule(
        frequency=PayFrequency.SEMI_MONTHLY,
        anchor_pay_date=date(2026, 1, 15),
        weekend_shift=WeekendShift.NONE,
    )
    dates = upcoming_pay_dates(s, date(2026, 2, 1), count=4)
    # 15th + 30th, with February capping the 30th to the 28th.
    assert [d["pay_date"] for d in dates] == [
        "2026-02-15",
        "2026-02-28",
        "2026-03-15",
        "2026-03-30",
    ]


def test_monthly_caps_the_31st():
    s = _schedule(
        frequency=PayFrequency.MONTHLY,
        anchor_pay_date=date(2026, 1, 31),
        weekend_shift=WeekendShift.NONE,
    )
    dates = upcoming_pay_dates(s, date(2026, 2, 1), count=3)
    assert [d["pay_date"] for d in dates] == ["2026-02-28", "2026-03-31", "2026-04-30"]


def test_weekend_shift_previous_and_next():
    # 2026-02-15 is a Sunday.
    base = dict(frequency=PayFrequency.SEMI_MONTHLY, anchor_pay_date=date(2026, 1, 15))
    prev = upcoming_pay_dates(
        _schedule(weekend_shift=WeekendShift.PREVIOUS_BUSINESS_DAY, **base),
        date(2026, 2, 10),
        count=1,
    )[0]
    nxt = upcoming_pay_dates(
        _schedule(weekend_shift=WeekendShift.NEXT_BUSINESS_DAY, **base),
        date(2026, 2, 10),
        count=1,
    )[0]
    none = upcoming_pay_dates(
        _schedule(weekend_shift=WeekendShift.NONE, **base), date(2026, 2, 10), count=1
    )[0]
    assert prev["pay_date"] == "2026-02-13" and prev["shifted"]
    assert nxt["pay_date"] == "2026-02-16" and nxt["shifted"]
    assert none["pay_date"] == "2026-02-15" and not none["shifted"]


def test_cutoff_derived_from_shifted_date():
    s = _schedule(submission_lead_days=3)
    d = upcoming_pay_dates(s, date(2026, 6, 1), count=1)[0]
    assert d["pay_date"] == "2026-06-12"
    assert d["submission_cutoff"] == "2026-06-09"


# --- API --------------------------------------------------------------------


def test_schedule_crud_and_upcoming(client):
    r = client.post(
        "/api/pay-schedules",
        json={
            "name": "Biweekly Friday",
            "frequency": "biweekly",
            "anchor_pay_date": "2026-01-09",
            "submission_lead_days": 2,
        },
    )
    assert r.status_code == 201, r.text
    sched = r.json()
    assert sched["weekend_shift"] == "previous_business_day"

    # Duplicate name rejected.
    r = client.post(
        "/api/pay-schedules",
        json={
            "name": "Biweekly Friday",
            "frequency": "biweekly",
            "anchor_pay_date": "2026-01-09",
        },
    )
    assert r.status_code == 400

    # Bad enums rejected.
    r = client.post(
        "/api/pay-schedules",
        json={
            "name": "Bad",
            "frequency": "fortnightly",
            "anchor_pay_date": "2026-01-09",
        },
    )
    assert r.status_code == 400

    r = client.get(
        f"/api/pay-schedules/{sched['id']}/upcoming?count=2&start=2026-06-01"
    )
    assert r.status_code == 200
    assert [d["pay_date"] for d in r.json()["dates"]] == ["2026-06-12", "2026-06-26"]

    r = client.put(f"/api/pay-schedules/{sched['id']}", json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_assign_employee_syncs_frequency(client):
    r = client.post(
        "/api/pay-schedules",
        json={
            "name": "Monthly 1st",
            "frequency": "monthly",
            "anchor_pay_date": "2026-01-01",
        },
    )
    sched = r.json()
    emp = client.post(
        "/api/employees",
        json={
            "first_name": "Pat",
            "last_name": "Worker",
            "pay_type": "salary",
            "pay_rate": 60000,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "WA",
        },
    ).json()

    r = client.post(f"/api/pay-schedules/{sched['id']}/assign/{emp['id']}")
    assert r.status_code == 200, r.text
    updated = client.get(f"/api/employees/{emp['id']}").json()
    assert updated["pay_frequency"] == "monthly"

    # Unknown ids 404.
    assert client.post(f"/api/pay-schedules/999/assign/{emp['id']}").status_code == 404
    assert (
        client.post(f"/api/pay-schedules/{sched['id']}/assign/999").status_code == 404
    )
