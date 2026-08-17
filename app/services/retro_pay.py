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

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.models.payroll import (
    Employee,
    PayRun,
    PayRunStatus,
    PayStub,
    PayType,
    periods_per_year,
)

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


def _stub_gross_at_rate(stub: PayStub, employee: Employee, rate: Decimal) -> Decimal:
    """What a processed stub's gross would have been at a different rate."""
    if employee.pay_type == PayType.SALARY:
        return _q(rate / periods_per_year(employee.pay_frequency))
    reg = Decimal(str(stub.regular_hours or 0))
    ot = Decimal(str(stub.overtime_hours or 0))
    dt = Decimal(str(stub.doubletime_hours or 0))
    if reg == 0 and ot == 0 and dt == 0:
        # Legacy stubs recorded only total hours — treat as all-regular.
        reg = Decimal(str(stub.hours or 0))
    return _q(reg * rate + ot * rate * Decimal("1.5") + dt * rate * Decimal("2"))


def compute_retro_pay(
    db, employee_id: int, new_rate: Decimal, effective_date: date
) -> dict:
    """The shortfall owed for periods already paid since `effective_date`.

    Compares each non-void stub with pay_date >= effective_date against
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
            PayRun.status != PayRunStatus.VOID,
            PayRun.pay_date >= effective_date,
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

    return {
        "employee_id": employee_id,
        "current_rate": float(Decimal(str(emp.pay_rate or 0))),
        "new_rate": float(new_rate),
        "effective_date": effective_date.isoformat(),
        "periods": periods,
        "retro_pay_due": float(_q(total)),
    }
