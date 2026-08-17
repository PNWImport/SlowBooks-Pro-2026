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
# Due dates falling on a weekend roll to the next Monday. Federal holidays
# are NOT modelled — a date landing on one is at most a day early, never
# late. State deposit frequencies vary too much to model here; state amounts
# appear on the quarterly return rows via compute_tax_liability.
# ============================================================================

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.models.payroll import PayRun, PayRunStatus, PayStub

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
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d += timedelta(days=1)
    return d


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
    return {
        "year": year,
        "lookback_start": start.isoformat(),
        "lookback_end": end.isoformat(),
        "lookback_quarters": quarters,
        "lookback_total": float(_q(total)),
        "threshold": float(LOOKBACK_THRESHOLD),
        "schedule": schedule,
        "note": (
            "New employers with no lookback history are monthly depositors "
            "by default."
            if total == 0
            else None
        ),
    }


# --- deposit events ---------------------------------------------------------


def _semiweekly_due(pay_date: date) -> date:
    """Wed-Fri pay dates -> following Wednesday; Sat-Tue -> following Friday."""
    wd = pay_date.weekday()  # Mon=0 ... Sun=6
    if wd in (2, 3, 4):  # Wed, Thu, Fri
        days_ahead = (2 - wd) % 7 or 7
    else:  # Sat, Sun, Mon, Tue
        days_ahead = (4 - wd) % 7 or 7
    return pay_date + timedelta(days=days_ahead)


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

    if schedule == "monthly":
        by_month: dict[int, Decimal] = {}
        for run in runs:
            by_month.setdefault(run.pay_date.month, Decimal("0"))
            by_month[run.pay_date.month] += _run_941_tax(run)
        for month, amount in sorted(by_month.items()):
            if amount <= 0:
                continue
            due_year, due_month = (year, month + 1) if month < 12 else (year + 1, 1)
            due = _next_business_day(date(due_year, due_month, 15))
            events.append(
                {
                    "period": f"{year}-{month:02d}",
                    "description": f"Monthly 941 deposit for {calendar.month_name[month]}",
                    "amount": float(_q(amount)),
                    "due_date": due.isoformat(),
                    "rule": "monthly",
                }
            )
    else:
        # Semiweekly: each pay date is its own accumulation, grouped by the
        # shared due date when several runs land in one window.
        by_due: dict[date, Decimal] = {}
        for run in runs:
            amount = _run_941_tax(run)
            if amount <= 0:
                continue
            due = _next_business_day(_semiweekly_due(run.pay_date))
            by_due.setdefault(due, Decimal("0"))
            by_due[due] += amount
        for due, amount in sorted(by_due.items()):
            events.append(
                {
                    "period": due.isoformat(),
                    "description": "Semiweekly 941 deposit",
                    "amount": float(_q(amount)),
                    "due_date": due.isoformat(),
                    "rule": "semiweekly",
                }
            )

    # $100k next-day rule — checked per pay date regardless of schedule.
    for run in runs:
        amount = _run_941_tax(run)
        if amount >= NEXT_DAY_THRESHOLD:
            due = _next_business_day(run.pay_date + timedelta(days=1))
            events.append(
                {
                    "period": run.pay_date.isoformat(),
                    "description": (
                        "NEXT-DAY deposit — accumulated $100,000+ on one day"
                    ),
                    "amount": float(_q(amount)),
                    "due_date": due.isoformat(),
                    "rule": "next_day",
                }
            )
            warnings.append(
                f"Pay date {run.pay_date.isoformat()} tripped the $100k "
                "next-day rule; the employer becomes a semiweekly depositor "
                "for the remainder of this year and all of next"
            )

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
