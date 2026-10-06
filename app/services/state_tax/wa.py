# ============================================================================
# Washington State payroll engine.
# ----------------------------------------------------------------------------
# Washington has NO state income tax. Its payroll burden comes from three
# wage/hour assessments:
#   * WA Paid Family & Medical Leave (PFML) — % of gross, split employee/employer
#   * WA Cares Fund — long-term-care premium, % of gross, employee only
#   * WA L&I workers' compensation — assessed PER HOUR worked, by risk class
#
# PFML / Cares rates follow ESD's 2026 employer guidance. Employer-size
# exemptions and employee Cares exemptions require separate configuration;
# this engine uses the standard employer share. L&I uses the risk-class rate.
# ============================================================================

from decimal import Decimal

from app.seed.wa_lni_rates import get_lni_rate
from app.services.accounting import _q
from app.services.state_tax.base import StateEngine, StateTaxResult

# --- WA Paid Family & Medical Leave -----------------------------------------
PFML_TOTAL_RATE = Decimal("0.0113")  # 2026 total premium, excluding tips
PFML_WAGE_BASE = Decimal("184500")  # 2026 Social Security cap
# https://paidleave.wa.gov/employer-roles-responsibilities/
PFML_EMPLOYEE_SHARE = Decimal("0.7143")  # employee pays 71.43% of the premium
PFML_EMPLOYER_SHARE = Decimal("0.2857")  # employer pays 28.57% of the premium

# --- WA Cares Fund (long-term care) -----------------------------------------
WA_CARES_RATE = Decimal("0.0058")  # employee-only, fraction of gross


class WAEngine(StateEngine):
    state_code: str = "WA"
    suta_wage_base: Decimal = Decimal("78200")

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
        tips: Decimal = Decimal("0"),
        ytd_tips: Decimal = Decimal("0"),
        **_extra,
    ) -> StateTaxResult:
        if gross <= 0:
            return StateTaxResult()

        # Both premiums use gross wages before income-tax deductions, excluding
        # reported and paycheck tips. Only Paid Leave has an annual cap.
        premium_wages = max(Decimal("0"), gross - Decimal(str(tips)))
        ytd_premium_wages = max(Decimal("0"), ytd_gross - Decimal(str(ytd_tips)))
        pfml_wages = max(
            Decimal("0"), min(premium_wages, PFML_WAGE_BASE - ytd_premium_wages)
        )
        pfml_total = pfml_wages * PFML_TOTAL_RATE
        pfml_employee = _q(pfml_total * PFML_EMPLOYEE_SHARE)
        pfml_employer = _q(pfml_total * PFML_EMPLOYER_SHARE)

        # WA Cares — employee-only long-term-care premium.
        wa_cares = _q(premium_wages * WA_CARES_RATE)

        # L&I workers' comp — per-hour rates by risk classification.
        rate = get_lni_rate(wc_class_code)
        lni_employee = _q(hours * rate["employee"])
        lni_employer = _q(hours * (rate["total"] - rate["employee"]))

        employee_other = pfml_employee + wa_cares + lni_employee
        employer_other = pfml_employer + lni_employer

        return StateTaxResult(
            income_tax=Decimal("0.00"),
            employee_other=employee_other,
            employer_other=employer_other,
            detail={
                "WA PFML (employee)": pfml_employee,
                "WA Cares": wa_cares,
                "WA L&I (employee)": lni_employee,
                "WA PFML (employer)": pfml_employer,
                "WA L&I (employer)": lni_employer,
            },
        )
