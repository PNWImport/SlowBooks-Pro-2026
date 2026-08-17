# ============================================================================
# Tipped wages — tip-credit top-up + the FICA tip credit (Form 8846).
# ----------------------------------------------------------------------------
# Two calculations:
#
#   * Top-up guarantee. An employer may pay a tipped cash wage below the
#     minimum (federal floor $2.13) only while cash wages + tips reach the
#     full minimum wage for the hours worked. When they don't, the employer
#     makes up the difference — computed per stub and added to gross wages.
#
#   * FICA tip credit (Form 8846). Food & beverage employers take a credit
#     for the employer-side FICA (7.65%) paid on tips ABOVE the amount
#     needed to bring the wage to $5.15/hour — the statutory pin, frozen at
#     the 2007 federal minimum regardless of today's floors.
#
# Form 8027 (large food establishments, allocated tips) needs gross-receipts
# tracking the app doesn't have; tracked in docs/todo.md.
# ============================================================================

from decimal import Decimal, ROUND_HALF_UP

from app.models.payroll import PayRun, PayRunStatus, PayStub

CENT = Decimal("0.01")

# Form 8846 statutory pin: employer FICA on tips above the amount needed to
# reach $5.15/hour is creditable.
FICA_TIP_CREDIT_WAGE_PIN = Decimal("5.15")
FICA_RATE = Decimal("0.0765")  # employer SS 6.2% + Medicare 1.45%


def _q(value) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value or 0))
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def tip_credit_topup(
    cash_wages: Decimal, tips: Decimal, hours: Decimal, minimum_wage: Decimal
) -> Decimal:
    """Employer make-up when cash wages + tips miss the minimum-wage floor."""
    hours = Decimal(str(hours or 0))
    if hours <= 0:
        return Decimal("0.00")
    required = Decimal(str(minimum_wage)) * hours
    earned = Decimal(str(cash_wages or 0)) + Decimal(str(tips or 0))
    return _q(max(Decimal("0"), required - earned))


def creditable_tips(cash_wages: Decimal, tips: Decimal, hours: Decimal) -> Decimal:
    """Tips above the amount needed to reach $5.15/hour — the 8846 base."""
    hours = Decimal(str(hours or 0))
    tips = Decimal(str(tips or 0))
    if tips <= 0:
        return Decimal("0.00")
    if hours <= 0:
        return _q(tips)
    shortfall = max(
        Decimal("0"), FICA_TIP_CREDIT_WAGE_PIN * hours - Decimal(str(cash_wages or 0))
    )
    return _q(max(Decimal("0"), tips - shortfall))


def compute_fica_tip_credit(db, year: int) -> dict:
    """Form 8846 summary: employer FICA on creditable tips, per employee."""
    from datetime import date

    stubs = (
        db.query(PayStub)
        .join(PayRun, PayStub.pay_run_id == PayRun.id)
        .filter(
            PayRun.status == PayRunStatus.PROCESSED,
            PayRun.pay_date >= date(year, 1, 1),
            PayRun.pay_date <= date(year, 12, 31),
        )
        .all()
    )

    by_employee: dict[int, dict] = {}
    total_creditable = Decimal("0")
    for s in stubs:
        tips = Decimal(str(s.reported_tips or 0)) + Decimal(str(s.paycheck_tips or 0))
        if tips <= 0:
            continue
        cash_wages = Decimal(str(s.gross_pay or 0)) - tips
        credit_base = creditable_tips(cash_wages, tips, s.hours)
        entry = by_employee.setdefault(
            s.employee_id,
            {
                "employee_id": s.employee_id,
                "name": s.employee.full_name if s.employee else None,
                "total_tips": Decimal("0"),
                "creditable_tips": Decimal("0"),
            },
        )
        entry["total_tips"] += tips
        entry["creditable_tips"] += credit_base
        total_creditable += credit_base

    employees = [
        {
            "employee_id": e["employee_id"],
            "name": e["name"],
            "total_tips": float(_q(e["total_tips"])),
            "creditable_tips": float(_q(e["creditable_tips"])),
            "credit": float(_q(e["creditable_tips"] * FICA_RATE)),
        }
        for e in sorted(by_employee.values(), key=lambda e: e["employee_id"])
    ]
    return {
        "year": year,
        "wage_pin": float(FICA_TIP_CREDIT_WAGE_PIN),
        "fica_rate": float(FICA_RATE),
        "total_creditable_tips": float(_q(total_creditable)),
        "total_credit": float(_q(total_creditable * FICA_RATE)),
        "employees": employees,
    }
