# ============================================================================
# Termination workflow — final-paycheck timing + PTO payout.
# ----------------------------------------------------------------------------
# Two questions every offboarding asks:
#
#   1. WHEN is the final paycheck due? State law, and it depends on whether
#      the departure was involuntary (fired/laid off) or voluntary (quit).
#      California: immediately on involuntary, 72 hours on voluntary with no
#      notice. Several states copy that shape; most default to the next
#      regular payday.
#
#   2. Must accrued vacation be PAID OUT? ~20 states treat accrued vacation
#      as earned wages that must be paid (CA, CO, IL, MA, ...). Elsewhere it
#      follows the employer's policy, so payout is an operator choice.
#
# The rules table below is APPROXIMATE and labelled per-state with its
# shape; deadlines are modelled as either a day count from termination or
# "next payday". Verify against the state's labor department before relying
# on it — final-paycheck statutes carry penalties (CA waiting-time penalty
# is a day of wages per day late, up to 30).
#
# Sick-leave balances are never auto-paid: almost no state requires it, and
# paying sick time out is an employer-policy decision the operator makes by
# passing include_sick=True.
# ============================================================================

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.models.payroll import Employee, PayType
from app.models.pto import PTOAccrual, PTOPolicy, PTOType

CENT = Decimal("0.01")

# Hours in a standard work year — converts an annual salary to an hourly
# equivalent for PTO payout (40 h/week × 52 weeks).
STANDARD_ANNUAL_HOURS = Decimal("2080")

# deadline encoding: {"days": N} = within N calendar days of termination
# (0 = same day / immediately); {"next_payday": True} = next regular payday.
_NEXT_PAYDAY = {"next_payday": True}

# state -> {involuntary, voluntary, pto_payout_required}
FINAL_PAYCHECK_RULES: dict[str, dict] = {
    "CA": {
        "involuntary": {"days": 0},
        "voluntary": {"days": 3},  # 72 hours without notice
        "pto_payout_required": True,
    },
    "CO": {
        "involuntary": {"days": 0},
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": True,
    },
    "MA": {
        "involuntary": {"days": 0},
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": True,
    },
    "MT": {
        "involuntary": {"days": 0},
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": True,
    },
    "NV": {
        "involuntary": {"days": 3},
        "voluntary": {"days": 7},
        "pto_payout_required": False,
    },
    "IL": {
        "involuntary": _NEXT_PAYDAY,
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": True,
    },
    "NE": {
        "involuntary": {"days": 14},
        "voluntary": {"days": 14},
        "pto_payout_required": True,
    },
    "ND": {
        "involuntary": _NEXT_PAYDAY,
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": True,
    },
    "RI": {
        "involuntary": _NEXT_PAYDAY,
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": True,
    },
    "MN": {
        "involuntary": {"days": 1},
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": False,
    },
    "MO": {
        "involuntary": {"days": 0},
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": False,
    },
    "OR": {
        "involuntary": {"days": 1},
        "voluntary": {"days": 5},
        "pto_payout_required": False,
    },
    "TX": {
        "involuntary": {"days": 6},
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": False,
    },
    "UT": {
        "involuntary": {"days": 1},
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": False,
    },
    "WA": {
        "involuntary": _NEXT_PAYDAY,
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": False,
    },
    "NY": {
        "involuntary": _NEXT_PAYDAY,
        "voluntary": _NEXT_PAYDAY,
        "pto_payout_required": False,
    },
}

# Everything not listed: next regular payday, payout per employer policy.
_DEFAULT_RULE = {
    "involuntary": _NEXT_PAYDAY,
    "voluntary": _NEXT_PAYDAY,
    "pto_payout_required": False,
}


def _q(value) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value or 0))
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def final_paycheck_rule(state: str | None, reason: str) -> dict:
    """The deadline encoding + payout flag for a state and departure reason.

    `reason` is "involuntary" or "voluntary"; anything else is treated as
    voluntary (the more lenient deadline — misclassifying a firing as a
    quit is the operator's error to fix, not ours to guess at).
    """
    rule = FINAL_PAYCHECK_RULES.get((state or "").strip().upper(), _DEFAULT_RULE)
    key = "involuntary" if reason == "involuntary" else "voluntary"
    return {
        "state": (state or "").strip().upper() or None,
        "deadline": rule[key],
        "pto_payout_required": rule["pto_payout_required"],
    }


def final_paycheck_deadline(
    state: str | None,
    reason: str,
    termination_date: date,
    next_regular_payday: date | None = None,
) -> dict:
    """Resolve the encoding to an actual date where possible."""
    rule = final_paycheck_rule(state, reason)
    deadline = rule["deadline"]
    if "days" in deadline:
        due = termination_date + timedelta(days=deadline["days"])
        description = (
            "immediately (day of termination)"
            if deadline["days"] == 0
            else f"within {deadline['days']} calendar days"
        )
    else:
        due = next_regular_payday
        description = "next regular payday"
    return {
        **rule,
        "due_date": due.isoformat() if due else None,
        "deadline_description": description,
    }


def hourly_equivalent_rate(employee: Employee) -> Decimal:
    """The rate PTO hours pay out at."""
    rate = Decimal(str(employee.pay_rate or 0))
    if employee.pay_type == PayType.SALARY:
        return _q(rate / STANDARD_ANNUAL_HOURS)
    return _q(rate)


def compute_pto_payout(db, employee: Employee, include_sick: bool = False) -> dict:
    """Accrued balances × the hourly-equivalent rate.

    Vacation and personal balances pay out; sick only when the operator
    opts in (no state requires it in this model).
    """
    accruals = (
        db.query(PTOAccrual)
        .join(PTOPolicy, PTOAccrual.policy_id == PTOPolicy.id)
        .filter(PTOAccrual.employee_id == employee.id)
        .all()
    )
    rate = hourly_equivalent_rate(employee)
    lines = []
    total_hours = Decimal("0")
    for accrual in accruals:
        policy = accrual.policy
        balance = Decimal(str(accrual.balance or 0))
        if balance <= 0:
            continue
        if policy.pto_type == PTOType.SICK and not include_sick:
            lines.append(
                {
                    "policy": policy.name,
                    "pto_type": policy.pto_type.value,
                    "hours": float(_q(balance)),
                    "included": False,
                    "amount": 0.0,
                }
            )
            continue
        amount = _q(balance * rate)
        total_hours += balance
        lines.append(
            {
                "policy": policy.name,
                "pto_type": policy.pto_type.value,
                "hours": float(_q(balance)),
                "included": True,
                "amount": float(amount),
            }
        )
    total = _q(total_hours * rate)
    return {
        "hourly_rate": float(rate),
        "total_hours": float(_q(total_hours)),
        "total_payout": float(total),
        "lines": lines,
    }
