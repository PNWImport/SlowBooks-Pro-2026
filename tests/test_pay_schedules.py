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
from app.services.federal_holidays import federal_reserve_holidays
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
    assert [d["pay_date"] for d in dates] == ["2026-06-05", "2026-06-12", "2026-06-18"]


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


def test_semi_monthly_rolls_into_next_year():
    s = _schedule(
        frequency=PayFrequency.SEMI_MONTHLY,
        anchor_pay_date=date(2026, 12, 20),
        weekend_shift=WeekendShift.NONE,
    )
    dates = upcoming_pay_dates(s, date(2026, 12, 20), count=4)
    assert [d["pay_date"] for d in dates] == [
        "2026-12-20",
        "2027-01-05",
        "2027-01-20",
        "2027-02-05",
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
    # Monday is Washington's Birthday, so the next business day is Tuesday.
    assert nxt["pay_date"] == "2026-02-17" and nxt["shifted"]
    assert none["pay_date"] == "2026-02-15" and not none["shifted"]


def test_federal_reserve_holiday_shift_and_saturday_rule():
    christmas = _schedule(
        frequency=PayFrequency.MONTHLY,
        anchor_pay_date=date(2026, 12, 25),
    )
    shifted = upcoming_pay_dates(christmas, date(2026, 12, 1), count=1)[0]
    assert shifted["pay_date"] == "2026-12-24"
    assert shifted["unshifted_date"] == "2026-12-25"

    # Reserve Banks are open Friday before a Saturday holiday.
    assert date(2027, 6, 18) not in federal_reserve_holidays(2027)
    assert date(2027, 7, 5) in federal_reserve_holidays(2027)  # Sunday observed


def test_custom_blackout_uses_selected_shift_direction():
    schedule = _schedule(
        frequency=PayFrequency.MONTHLY,
        anchor_pay_date=date(2026, 8, 17),
        blackout_dates=["2026-08-17"],
    )
    shifted = upcoming_pay_dates(schedule, date(2026, 8, 1), count=1)[0]
    assert shifted["pay_date"] == "2026-08-14"

    schedule.weekend_shift = WeekendShift.NEXT_BUSINESS_DAY
    shifted = upcoming_pay_dates(schedule, date(2026, 8, 1), count=1)[0]
    assert shifted["pay_date"] == "2026-08-18"


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
            "blackout_dates": ["2026-06-12", "2026-06-12"],
        },
    )
    assert r.status_code == 201, r.text
    sched = r.json()
    assert sched["weekend_shift"] == "previous_business_day"
    assert sched["blackout_dates"] == ["2026-06-12"]

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
    assert [d["pay_date"] for d in r.json()["dates"]] == ["2026-06-11", "2026-06-26"]

    r = client.put(f"/api/pay-schedules/{sched['id']}", json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_schedule_blackouts_can_be_cleared_and_invalid_dates_rejected(client):
    created = client.post(
        "/api/pay-schedules",
        json={
            "name": "Blackout Test",
            "frequency": "monthly",
            "anchor_pay_date": "2026-08-17",
            "blackout_dates": ["2026-08-17"],
        },
    ).json()
    assert created["blackout_dates"] == ["2026-08-17"]
    cleared = client.put(
        f"/api/pay-schedules/{created['id']}", json={"blackout_dates": []}
    )
    assert cleared.status_code == 200
    assert cleared.json()["blackout_dates"] == []
    invalid = client.put(
        f"/api/pay-schedules/{created['id']}",
        json={"blackout_dates": ["not-a-date"]},
    )
    assert invalid.status_code == 422


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

    changed = client.put(
        f"/api/pay-schedules/{sched['id']}", json={"frequency": "weekly"}
    )
    assert changed.status_code == 200
    updated = client.get(f"/api/employees/{emp['id']}").json()
    assert updated["pay_frequency"] == "weekly"

    # Unknown ids 404.
    assert client.post(f"/api/pay-schedules/999/assign/{emp['id']}").status_code == 404
    assert (
        client.post(f"/api/pay-schedules/{sched['id']}/assign/999").status_code == 404
    )

    assert (
        client.put(
            f"/api/pay-schedules/{sched['id']}", json={"is_active": False}
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/pay-schedules/{sched['id']}/assign/{emp['id']}").status_code
        == 400
    )


def test_schedule_name_and_lead_validation(client):
    first = client.post(
        "/api/pay-schedules",
        json={
            "name": "First",
            "frequency": "monthly",
            "anchor_pay_date": "2026-01-01",
        },
    ).json()
    second = client.post(
        "/api/pay-schedules",
        json={
            "name": "Second",
            "frequency": "monthly",
            "anchor_pay_date": "2026-01-01",
        },
    ).json()
    duplicate = client.put(
        f"/api/pay-schedules/{second['id']}", json={"name": first["name"]}
    )
    assert duplicate.status_code == 400
    assert client.get(f"/api/pay-schedules/{second['id']}/upcoming").status_code == 200

    blank = client.post(
        "/api/pay-schedules",
        json={
            "name": "   ",
            "frequency": "monthly",
            "anchor_pay_date": "2026-01-01",
        },
    )
    assert blank.status_code == 400
    too_long = client.put(
        f"/api/pay-schedules/{first['id']}", json={"submission_lead_days": 366}
    )
    assert too_long.status_code == 422
