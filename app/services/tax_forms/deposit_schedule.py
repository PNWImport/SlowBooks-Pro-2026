# ============================================================================
# Federal deposit schedule + payroll tax liability calendar.
# ----------------------------------------------------------------------------
# The honest, local-only version of a payroll provider's "we handle your
# taxes": tell the operator exactly WHAT is due, to WHOM, and WHEN — without
# claiming to pay it.
#
# Deposit-schedule determination (IRS Pub 15 §11):
#   * Lookback period for calendar year Y = July 1 of Y-2 through June 30 of
#     Y-1 (four quarters). Total Form 941 tax in that window:
#       <= $50,000  -> MONTHLY depositor: each month's liability is due the
#                      15th of the following month.
#       >  $50,000  -> SEMIWEEKLY depositor: pay dates Wed-Fri deposit by the
#                      following Wednesday; Sat-Tue by the following Friday.
#   * $100,000 next-day rule: accumulate $100k+ of 941 liability on any day
#     and the deposit is due the NEXT business day, regardless of schedule
#     (and the employer becomes semiweekly for the rest of this year and all
#     of next — surfaced as a warning, not persisted).
#   * De minimis: a full quarter under $2,500 may be paid with the return.
#
# FUTA deposits quarterly once the cumulative undeposited amount exceeds
# $500, due the last day of the month after the quarter; under $500 it rolls
# forward (Q4 remainder rides the annual Form 940).
#
# Federal due dates roll across weekends and District of Columbia legal
# holidays. Semiweekly deadlines retain the IRS-required three business days
# after the deposit period closes. State deposit frequencies vary too much to
# model here; state amounts appear on quarterly return rows as reminders.
# ============================================================================

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.models.payroll import PayRun, PayRunStatus, PayStub
from app.services.federal_holidays import (
    add_federal_tax_business_days,
    next_federal_tax_business_day,
)

CENT = Decimal("0.01")

LOOKBACK_THRESHOLD = Decimal("50000")
NEXT_DAY_THRESHOLD = Decimal("100000")
DE_MINIMIS = Decimal("2500")
FUTA_DEPOSIT_FLOOR = Decimal("500")


def _q(value) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value or 0))
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _next_business_day(d: date) -> date:
    """Backward-compatible local name for the federal tax calendar helper."""
    return next_federal_tax_business_day(d)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _stub_941_tax(stub: PayStub) -> Decimal:
    """One stub's Form 941 liability: federal withholding + both FICA sides."""
    return (
        _q(stub.federal_tax)
        + _q(stub.ss_tax)
        + _q(stub.employer_ss_tax)
        + _q(stub.medicare_tax)
        + _q(stub.employer_medicare_tax)
    )


def _runs_in_window(db, start: date, end: date):
    return (
        db.query(PayRun)
        .filter(
            PayRun.status == PayRunStatus.PROCESSED,
            PayRun.pay_date >= start,
            PayRun.pay_date <= end,
        )
        .order_by(PayRun.pay_date)
        .all()
    )


def _run_941_tax(run: PayRun) -> Decimal:
    return sum((_stub_941_tax(s) for s in run.stubs), Decimal("0"))


# --- lookback ---------------------------------------------------------------


def determine_deposit_schedule(db, year: int) -> dict:
    """Classify the employer as a monthly or semiweekly depositor for `year`.

    Uses the Pub 15 lookback period: the four quarters from July 1 of
    year-2 through June 30 of year-1.
    """
    start = date(year - 2, 7, 1)
    end = date(year - 1, 6, 30)
    quarters = []
    total = Decimal("0")
    for qy, qq in [(year - 2, 3), (year - 2, 4), (year - 1, 1), (year - 1, 2)]:
        q_start = date(qy, (qq - 1) * 3 + 1, 1)
        q_end = _month_end(qy, qq * 3)
        q_total = sum(
            (_run_941_tax(r) for r in _runs_in_window(db, q_start, q_end)),
            Decimal("0"),
        )
        quarters.append({"year": qy, "quarter": qq, "form_941_tax": float(_q(q_total))})
        total += q_total

    schedule = "monthly" if total <= LOOKBACK_THRESHOLD else "semiweekly"
    prior_lookback_start = date(year - 3, 7, 1)
    prior_lookback_end = date(year - 2, 6, 30)
    prior_lookback_total = sum(
        (
            _run_941_tax(run)
            for run in _runs_in_window(db, prior_lookback_start, prior_lookback_end)
        ),
        Decimal("0"),
    )
    prior_starting_schedule = (
        "monthly" if prior_lookback_total <= LOOKBACK_THRESHOLD else "semiweekly"
    )
    next_day_carryover = _year_tripped_next_day_rule(
        db, year - 1, prior_starting_schedule
    )
    if next_day_carryover:
        schedule = "semiweekly"
    return {
        "year": year,
        "lookback_start": start.isoformat(),
        "lookback_end": end.isoformat(),
        "lookback_quarters": quarters,
        "lookback_total": float(_q(total)),
        "threshold": float(LOOKBACK_THRESHOLD),
        "schedule": schedule,
        "next_day_carryover": next_day_carryover,
        "note": (
            "A $100,000 next-day event in the prior year requires the "
            "semiweekly schedule this year."
            if next_day_carryover
            else (
                "New employers with no lookback history are monthly depositors "
                "by default."
                if total == 0
                else None
            )
        ),
    }


# --- deposit events ---------------------------------------------------------


def _semiweekly_due(pay_date: date) -> date:
    """Third federal business day after the semiweekly deposit period closes."""
    wd = pay_date.weekday()  # Mon=0 ... Sun=6
    if wd in (2, 3, 4):  # Wed, Thu, Fri
        period_end = pay_date + timedelta(days=4 - wd)  # Friday
    else:  # Sat, Sun, Mon, Tue
        period_end = pay_date + timedelta(days=(1 - wd) % 7)  # Tuesday
    return add_federal_tax_business_days(period_end, 3)


def _normal_deposit_bucket(pay_date: date, schedule: str) -> dict:
    """Grouping and display metadata for a non-next-day 941 obligation."""
    if schedule == "monthly":
        due_year, due_month = (
            (pay_date.year, pay_date.month + 1)
            if pay_date.month < 12
            else (pay_date.year + 1, 1)
        )
        due = _next_business_day(date(due_year, due_month, 15))
        return {
            "key": (schedule, pay_date.year, pay_date.month),
            "period": f"{pay_date.year}-{pay_date.month:02d}",
            "description": (
                f"Monthly 941 deposit for {calendar.month_name[pay_date.month]}"
            ),
            "due": due,
            "rule": schedule,
        }

    due = _semiweekly_due(pay_date)
    quarter = (pay_date.month - 1) // 3 + 1
    return {
        # Liabilities from different 941 return periods require separate
        # deposits even when their semiweekly due date is the same.
        "key": (schedule, due, pay_date.year, quarter),
        "period": due.isoformat(),
        "description": "Semiweekly 941 deposit",
        "due": due,
        "rule": schedule,
    }


def _year_tripped_next_day_rule(db, year: int, starting_schedule: str) -> bool:
    """Whether accumulated 941 tax reached $100k in any prior-year period."""
    daily: dict[date, Decimal] = {}
    for run in _runs_in_window(db, date(year, 1, 1), date(year, 12, 31)):
        daily.setdefault(run.pay_date, Decimal("0"))
        daily[run.pay_date] += _run_941_tax(run)

    active_schedule = starting_schedule
    period_key = None
    accumulated = Decimal("0")
    for pay_date, amount in sorted(daily.items()):
        key = _normal_deposit_bucket(pay_date, active_schedule)["key"]
        if key != period_key:
            period_key = key
            accumulated = Decimal("0")
        accumulated += amount
        if accumulated >= NEXT_DAY_THRESHOLD:
            return True
    return False


def federal_deposit_events(db, year: int, schedule: str | None = None) -> dict:
    """The year's federal 941 deposit obligations under the given schedule.

    When `schedule` is None it is determined from the lookback. Returns the
    deposit events (grouped per month or per semiweekly window), with the
    $100k next-day rule applied per accumulation period and de-minimis
    quarters flagged.
    """
    determination = determine_deposit_schedule(db, year)
    if schedule is None:
        schedule = determination["schedule"]
    if schedule not in ("monthly", "semiweekly"):
        raise ValueError("schedule must be 'monthly' or 'semiweekly'")

    runs = _runs_in_window(db, date(year, 1, 1), date(year, 12, 31))
    events: list[dict] = []
    warnings: list[str] = []

    # Aggregate all runs paid on one date before evaluating the $100k rule.
    # A next-day event consumes the accumulated normal obligation so the same
    # dollars never appear a second time under monthly/semiweekly output.
    by_day: dict[date, Decimal] = {}
    for run in runs:
        by_day.setdefault(run.pay_date, Decimal("0"))
        by_day[run.pay_date] += _run_941_tax(run)

    active_schedule = schedule
    pending_meta = None
    pending_amount = Decimal("0")

    def flush_pending():
        nonlocal pending_meta, pending_amount
        if pending_meta is not None and pending_amount > 0:
            events.append(
                {
                    "period": pending_meta["period"],
                    "description": pending_meta["description"],
                    "amount": float(_q(pending_amount)),
                    "due_date": pending_meta["due"].isoformat(),
                    "rule": pending_meta["rule"],
                }
            )
        pending_meta = None
        pending_amount = Decimal("0")

    for pay_date, daily_amount in sorted(by_day.items()):
        if daily_amount <= 0:
            continue
        meta = _normal_deposit_bucket(pay_date, active_schedule)
        if pending_meta is not None and pending_meta["key"] != meta["key"]:
            flush_pending()
        if pending_meta is None:
            pending_meta = meta
        pending_amount += daily_amount

        if pending_amount >= NEXT_DAY_THRESHOLD:
            changed_schedule = active_schedule == "monthly"
            due = _next_business_day(pay_date + timedelta(days=1))
            events.append(
                {
                    "period": pay_date.isoformat(),
                    "description": (
                        "NEXT-DAY deposit — accumulated $100,000+ through this day"
                    ),
                    "amount": float(_q(pending_amount)),
                    "due_date": due.isoformat(),
                    "rule": "next_day",
                }
            )
            pending_meta = None
            pending_amount = Decimal("0")
            active_schedule = "semiweekly"
            warning = f"Pay date {pay_date.isoformat()} tripped the $100k next-day rule"
            if changed_schedule:
                warning += (
                    "; the employer becomes a semiweekly depositor for the "
                    "remainder of this year and all of next"
                )
            warnings.append(warning)

    flush_pending()

    # De-minimis quarters: full quarterly liability under $2,500 may ride
    # the 941 return instead of separate deposits.
    for quarter in (1, 2, 3, 4):
        q_start = date(year, (quarter - 1) * 3 + 1, 1)
        q_end = _month_end(year, quarter * 3)
        q_total = sum(
            (_run_941_tax(r) for r in _runs_in_window(db, q_start, q_end)),
            Decimal("0"),
        )
        if Decimal("0") < q_total < DE_MINIMIS:
            warnings.append(
                f"Q{quarter} total 941 liability {float(_q(q_total))} is under "
                "the $2,500 de-minimis — it may be paid with the quarterly "
                "return instead of deposited"
            )

    events.sort(key=lambda e: e["due_date"])
    return {
        "year": year,
        "schedule": schedule,
        "determination": determination,
        "events": events,
        "warnings": warnings,
    }


# --- FUTA -------------------------------------------------------------------


def futa_deposit_events(db, year: int) -> list[dict]:
    """Quarterly FUTA deposits: due once cumulative undeposited FUTA > $500."""
    events = []
    carried = Decimal("0")
    for quarter in (1, 2, 3, 4):
        q_start = date(year, (quarter - 1) * 3 + 1, 1)
        q_end = _month_end(year, quarter * 3)
        q_futa = Decimal("0")
        for run in _runs_in_window(db, q_start, q_end):
            q_futa += sum((_q(s.futa_tax) for s in run.stubs), Decimal("0"))
        carried += q_futa
        if carried > FUTA_DEPOSIT_FLOOR:
            due_month = quarter * 3 + 1
            due_year = year
            if due_month > 12:
                due_month, due_year = 1, year + 1
            due = _next_business_day(_month_end(due_year, due_month))
            events.append(
                {
                    "period": f"{year}-Q{quarter}",
                    "description": f"FUTA deposit for Q{quarter}"
                    + (" (includes carryover)" if carried != q_futa else ""),
                    "amount": float(_q(carried)),
                    "due_date": due.isoformat(),
                    "rule": "futa_quarterly",
                }
            )
            carried = Decimal("0")
    if carried > 0:
        events.append(
            {
                "period": f"{year}-Q4",
                "description": "Remaining FUTA (under $500) — pay with Form 940",
                "amount": float(_q(carried)),
                "due_date": _next_business_day(date(year + 1, 1, 31)).isoformat(),
                "rule": "futa_with_return",
            }
        )
    return events


# --- the calendar -----------------------------------------------------------


def liability_calendar(db, year: int) -> dict:
    """Everything payroll owes for a year, merged and date-sorted.

    Federal 941 deposits (by determined schedule), FUTA deposits, and the
    quarterly return due dates (941 filing, state SUI, state withholding —
    amounts from compute_tax_liability). State deposit FREQUENCIES vary by
    state and are not modelled; state rows carry the quarterly return date.
    """
    from app.services.tax_forms.tax_liability import compute_tax_liability

    federal = federal_deposit_events(db, year)
    entries = list(federal["events"])
    entries.extend(futa_deposit_events(db, year))

    for quarter in (1, 2, 3, 4):
        liab = compute_tax_liability(db, year, quarter)
        for row in liab["liabilities"]:
            if row["form"] in ("941",):
                entries.append(
                    {
                        "period": f"{year}-Q{quarter}",
                        "description": f"File Form 941 for Q{quarter}",
                        "amount": row["amount"],
                        "due_date": row["due_date"],
                        "rule": "return_941",
                    }
                )
            elif row["form"] in ("State SUI", "State WH", "State Other"):
                if row["amount"] > 0:
                    entries.append(
                        {
                            "period": f"{year}-Q{quarter}",
                            "description": f"{row['description']} (Q{quarter}) — "
                            "check your state's deposit frequency",
                            "amount": row["amount"],
                            "due_date": row["due_date"],
                            "rule": "state_quarterly",
                        }
                    )

    # Annual Form 940.
    entries.append(
        {
            "period": str(year),
            "description": f"File Form 940 (FUTA) for {year}",
            "amount": None,
            "due_date": _next_business_day(date(year + 1, 1, 31)).isoformat(),
            "rule": "return_940",
        }
    )

    entries.sort(key=lambda e: (e["due_date"], e["description"]))
    return {
        "year": year,
        "schedule": federal["schedule"],
        "warnings": federal["warnings"],
        "entries": entries,
    }
