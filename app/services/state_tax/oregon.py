# ============================================================================
# Oregon State payroll engine.
# ----------------------------------------------------------------------------
# Module named "oregon" rather than "or" — `or` is a Python keyword and cannot
# be imported under its 2-letter code.
#
# Oregon withholds a progressive state income tax, statewide transit tax,
# and Paid Leave Oregon contributions. Paid Leave uses the standard covered,
# large-employer split; employer-size/assistance-grant classifications,
# equivalent plans, employee coverage exceptions, and employer-paid employee
# shares are not inferred or configured here.
#
# Income-tax brackets and the standard deduction are 2026-approximate,
# simplified figures modelled on the published Oregon DOR schedule structure.
# Verify against the current Oregon withholding tables before relying on these
# for actual tax filing.
# ============================================================================

from decimal import Decimal

from app.services.accounting import _q
from app.services.state_tax.base import StateEngine, StateTaxResult

# --- Oregon statewide transit tax -------------------------------------------
TRANSIT_TAX_RATE = Decimal("0.001")  # 0.1% of gross, employee

# --- Paid Leave Oregon, 2026 ------------------------------------------------
# https://paidleave.oregon.gov/employers/contributions-calculator.html
PAID_LEAVE_RATE = Decimal("0.01")
PAID_LEAVE_WAGE_BASE = Decimal("184500")
PAID_LEAVE_EMPLOYEE_SHARE = Decimal("0.60")
PAID_LEAVE_EMPLOYER_SHARE = Decimal("0.40")

# --- Oregon income tax (2026-approximate, simplified) -----------------------
STD_DEDUCTION = {
    "single": Decimal("2745"),
    "head_of_household": Decimal("4420"),
    "married": Decimal("5495"),
}

# Annual progressive brackets as ascending (lower_bound, marginal_rate) pairs.
_BRACKETS = {
    "single": [
        (Decimal("0"), Decimal("0.0475")),
        (Decimal("4300"), Decimal("0.0675")),
        (Decimal("10750"), Decimal("0.0875")),
        (Decimal("125000"), Decimal("0.099")),
    ],
    "married": [
        (Decimal("0"), Decimal("0.0475")),
        (Decimal("8600"), Decimal("0.0675")),
        (Decimal("21500"), Decimal("0.0875")),
        (Decimal("250000"), Decimal("0.099")),
    ],
}


def _tax_from_brackets(wage: Decimal, brackets) -> Decimal:
    """Progressive tax on `wage` given ascending (lower_bound, rate) brackets."""
    if wage <= 0:
        return Decimal("0")
    tax = Decimal("0")
    for i, (lower, rate) in enumerate(brackets):
        if wage <= lower:
            break
        upper = brackets[i + 1][0] if i + 1 < len(brackets) else None
        top = wage if upper is None else min(wage, upper)
        tax += (top - lower) * rate
        if upper is None or wage <= upper:
            break
    return tax


class OregonEngine(StateEngine):
    state_code: str = "OR"
    suta_wage_base: Decimal = Decimal("56700")

    def calculate(
        self,
        *,
        gross: Decimal,
        taxable: Decimal,
        ytd_gross: Decimal,
        pay_periods: int,
        hours: Decimal,
        filing_status: str,
        wc_class_code: str | None,
        fica_wages: Decimal | None = None,
        ytd_fica_wages: Decimal | None = None,
        **_extra,
    ) -> StateTaxResult:
        if gross <= 0:
            return StateTaxResult()

        fs = filing_status if filing_status in _BRACKETS else "single"

        # Income tax — annualize, apply brackets net of the standard deduction,
        # then divide back down to the period amount.
        annual = taxable * pay_periods
        annual_taxable = annual - STD_DEDUCTION[fs]
        if annual_taxable < 0:
            annual_taxable = Decimal("0")
        annual_tax = _tax_from_brackets(annual_taxable, _BRACKETS[fs])
        income_tax = _q(annual_tax / pay_periods)

        # Statewide transit tax — flat 0.1% of gross, employee.
        transit_tax = _q(gross * TRANSIT_TAX_RATE)

        # For the supported ordinary wage/benefit categories, Paid Leave
        # includes tips and retirement salary deferrals but excludes qualified
        # Section 125 health/FSA/HSA deductions. The payroll calculator supplies
        # these current and immutable historical bases separately from income
        # tax wages. Standalone callers without exclusions retain gross bases.
        # https://paidleave.oregon.gov/resources/
        subject_wages = gross if fica_wages is None else Decimal(str(fica_wages))
        ytd_subject = (
            ytd_gross if ytd_fica_wages is None else Decimal(str(ytd_fica_wages))
        )
        paid_leave_wages = max(
            Decimal("0"), min(subject_wages, PAID_LEAVE_WAGE_BASE - ytd_subject)
        )
        paid_leave_employee = _q(
            paid_leave_wages * PAID_LEAVE_RATE * PAID_LEAVE_EMPLOYEE_SHARE
        )
        paid_leave_employer = _q(
            paid_leave_wages * PAID_LEAVE_RATE * PAID_LEAVE_EMPLOYER_SHARE
        )

        return StateTaxResult(
            income_tax=income_tax,
            employee_other=transit_tax + paid_leave_employee,
            employer_other=paid_leave_employer,
            detail={
                "OR income tax": income_tax,
                "OR statewide transit tax": transit_tax,
                "OR Paid Leave (employee)": paid_leave_employee,
                "OR Paid Leave (employer)": paid_leave_employer,
            },
        )
