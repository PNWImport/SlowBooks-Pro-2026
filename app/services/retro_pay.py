# ============================================================================
# Retro pay + mid-period rate proration.
# ----------------------------------------------------------------------------
# Two related problems around "the rate changed":
#
#   * Mid-period proration — the raise lands INSIDE the current pay period.
#     Salary: day-weight the period's salary across the two rates. Hourly:
#     the caller already knows the hour split; the blend is arithmetic.
#
#   * Retro pay — the raise is effective in the PAST, and periods paid since
#     then used the old rate. Compute what each processed stub would have
#     paid at the new rate and sum the shortfall, to be paid out as a
#     supplemental earning on an off-cycle run (supplemental wages, so the
#     flat-rate withholding path applies).
#
# Retro on hourly stubs re-prices the recorded hour split (regular / 1.5x
# overtime / 2x doubletime); retro on salary stubs is the per-period salary
# difference. Stubs on VOID runs are ignored. A rate DECREASE produces a
# negative preview and is rejected at apply time — clawing back paid wages
# is a legal question, not a payroll calculation.
# ============================================================================

import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.models.payroll import (
    Employee,
    PayRun,
    PayRunStatus,
    PayStub,
    PayFrequency,
    periods_per_year,
)


class RetroPayConflict(ValueError):
    """Source earnings or earlier retro claims need explicit reconciliation."""


CENT = Decimal("0.01")


def _q(value) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value or 0))
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def prorated_salary_gross(
    annual_old: Decimal,
    annual_new: Decimal,
    frequency,
    period_start: date,
    period_end: date,
    change_date: date,
) -> Decimal:
    """Day-weighted period gross when a salary changes mid-period.

    Days before `change_date` pay at the old rate; `change_date` itself and
    after pay at the new rate. A change on/before period_start is entirely
    new-rate; after period_end entirely old-rate.
    """
    periods = periods_per_year(frequency)
    old_period = Decimal(str(annual_old)) / periods
    new_period = Decimal(str(annual_new)) / periods

    total_days = (period_end - period_start).days + 1
    if total_days <= 0:
        return Decimal("0.00")
    if change_date <= period_start:
        return _q(new_period)
    if change_date > period_end:
        return _q(old_period)

    days_old = (change_date - period_start).days
    days_new = total_days - days_old
    blended = (old_period * days_old + new_period * days_new) / total_days
    return _q(blended)


def _stub_gross_at_rate(stub: PayStub, employee: Employee, rate: Decimal):
    """Reprice recorded rate-derived earnings, preserving fixed original tips.

    None means an explicitly override-priced or zero-wage check. We do not
    infer historical salary frequency, proration or a minimum-wage law. A
    recorded top-up preserves the gross floor already guaranteed on that
    check rather than silently subtracting it from a raise's arrears.
    """
    try:
        detail = json.loads(stub.detail_json or "null")
    except (TypeError, ValueError):
        detail = None
    earnings = detail.get("_payroll_earnings") if isinstance(detail, dict) else None
    if not stub.gross_pay:
        return None
    if earnings is not None:
        if not isinstance(earnings, dict) or earnings.get("version") != 1:
            raise RetroPayConflict(
                "Historical earnings snapshot is unverified; review this retro payment."
            )
        source = earnings.get("source")
        if source == "override":
            return None
        if source not in ("salary", "hourly"):
            raise RetroPayConflict(
                "Historical earnings source is unverified; review this retro payment."
            )
    else:
        raise RetroPayConflict(
            "Historical rate-derived earnings are unverified; review legacy payroll before applying retro pay."
        )
    if employee.pay_type is None or source != employee.pay_type.value:
        raise RetroPayConflict(
            "Historical and current pay types use different rate units. "
            "Reconcile the hourly/salary conversion before applying retro pay."
        )
    tips = Decimal(str(stub.reported_tips or 0)) + Decimal(str(stub.paycheck_tips or 0))
    if source == "salary":
        if (
            not isinstance(earnings.get("prorated_salary"), bool)
            or earnings["prorated_salary"]
        ):
            raise RetroPayConflict(
                "Prorated salary requires explicit retro reconciliation; no historical rates were inferred."
            )
        try:
            frequency = PayFrequency(earnings["pay_frequency"])
        except (KeyError, ValueError, TypeError) as exc:
            raise RetroPayConflict(
                "Historical salary frequency is unverified; review this retro payment."
            ) from exc
        return _q(rate / periods_per_year(frequency) + tips)
    reg = Decimal(str(stub.regular_hours or 0))
    ot = Decimal(str(stub.overtime_hours or 0))
    dt = Decimal(str(stub.doubletime_hours or 0))
    if reg + ot + dt <= 0:
        raise RetroPayConflict(
            "Historical hourly earnings have no verified hours; review this retro payment."
        )
    repriced = _q(
        reg * rate + ot * rate * Decimal("1.5") + dt * rate * Decimal("2") + tips
    )
    if stub.tip_credit_topup:
        repriced = max(repriced, Decimal(str(stub.gross_pay)))
    return repriced


def compute_retro_pay(
    db, employee_id: int, new_rate: Decimal, effective_date: date
) -> dict:
    """The shortfall owed for periods already paid since `effective_date`.

    Compares each processed stub with pay_date >= effective_date against
    what it would have paid at `new_rate`. Off-cycle/bonus stubs with a
    gross override re-price to the same figure (their gross wasn't
    rate-derived), so they contribute zero — correct, since a bonus isn't
    underpaid by a raise.
    """
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if emp is None:
        raise ValueError(f"Employee {employee_id} not found")
    new_rate = Decimal(str(new_rate))

    stubs = (
        db.query(PayStub)
        .join(PayRun, PayStub.pay_run_id == PayRun.id)
        .filter(
            PayStub.employee_id == employee_id,
            PayRun.status == PayRunStatus.PROCESSED,
            PayRun.period_end >= effective_date,
        )
        .order_by(PayRun.pay_date)
        .all()
    )

    periods = []
    total = Decimal("0")
    for stub in stubs:
        run = stub.pay_run
        # Bonus / off-cycle runs are override-priced, not rate-derived.
        if run.run_type and run.run_type.value != "regular":
            continue
        paid = Decimal(str(stub.gross_pay or 0))
        would_have = _stub_gross_at_rate(stub, emp, new_rate)
        if would_have is None:
            continue
        if run.period_start < effective_date:
            raise RetroPayConflict(
                "The raise begins inside a paid work period with no verified "
                "hour/rate split. Reconcile that partial period before applying retro pay."
            )
        diff = _q(would_have - paid)
        periods.append(
            {
                "pay_run_id": run.id,
                "pay_date": run.pay_date.isoformat(),
                "paid_gross": float(_q(paid)),
                "gross_at_new_rate": float(would_have),
                "difference": float(diff),
            }
        )
        total += diff

    owed_run_ids = {
        period["pay_run_id"] for period in periods if period["difference"] > 0
    }
    if owed_run_ids:
        _refuse_overlapping_retro(db, employee_id, owed_run_ids)

    return {
        "employee_id": employee_id,
        "current_rate": float(Decimal(str(emp.pay_rate or 0))),
        "new_rate": float(new_rate),
        "effective_date": effective_date.isoformat(),
        "periods": periods,
        "retro_pay_due": float(_q(total)),
    }


def _refuse_overlapping_retro(db, employee_id, owed_run_ids, *, exclude_run_id=None):
    """Reserve source claims on new drafts; never allocate old retro dollars."""
    adjustments = (
        db.query(PayStub)
        .join(PayRun, PayStub.pay_run_id == PayRun.id)
        .filter(PayStub.employee_id == employee_id, PayRun.status != PayRunStatus.VOID)
        .all()
    )
    for adjustment in adjustments:
        if adjustment.pay_run_id == exclude_run_id:
            continue
        try:
            detail = json.loads(adjustment.detail_json or "null")
        except (TypeError, ValueError):
            continue
        if not isinstance(detail, dict) or "retro_pay" not in detail:
            continue
        claimed = detail.get("retro_source_run_ids")
        if (
            not isinstance(claimed, list)
            or not claimed
            or any(
                not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0
                for run_id in claimed
            )
            or len(claimed) != len(set(claimed))
        ):
            raise RetroPayConflict(
                "An earlier retro adjustment has no verified source claims. Reconcile it before paying more retro wages; no historical amounts were inferred."
            )
        if owed_run_ids.intersection(claimed):
            raise RetroPayConflict(
                "A pending or processed retro adjustment already claims these paid periods. Cancel the pending draft or reconcile the paid adjustment before applying another raise."
            )
