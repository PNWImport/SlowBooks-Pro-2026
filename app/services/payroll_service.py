# ============================================================================
# Payroll Service — federal withholding (IRS Pub 15-T) + FICA + employer taxes
# ----------------------------------------------------------------------------
# Federal income tax withholding follows Pub 15-T Worksheet 1A (Percentage
# Method for Automated Payroll Systems) using the 2020+ redesigned Form W-4 —
# there are no "allowances" anymore. Supplemental wages use Worksheet 4 (flat).
#
# Annual federal schedules match the published 2026 Pub 15-T, section 1.
# State and employer-specific payroll settings require their own verification.
# ============================================================================

from decimal import Decimal

from app.models.payroll import periods_per_year
from app.services.accounting import _q
from app.services.state_tax import get_engine

# --- FICA -------------------------------------------------------------------
SS_RATE = Decimal("0.062")  # Social Security 6.2% (employee & employer each)
SS_WAGE_BASE = Decimal("184500")  # 2026 SSA contribution and benefit base
MEDICARE_RATE = Decimal("0.0145")  # Medicare 1.45% (employee & employer each)
MEDICARE_ADDITIONAL_RATE = Decimal("0.009")  # extra 0.9% (employee only)
MEDICARE_ADDITIONAL_THRESHOLD = Decimal("200000")  # withhold the extra above this

# --- Federal unemployment (FUTA) -------------------------------------------
FUTA_WAGE_BASE = Decimal("7000")
FUTA_EFFECTIVE_RATE = Decimal("0.006")  # 6.0% gross less the standard 5.4% state credit

# --- Pub 15-T Worksheet 1A -------------------------------------------------
# Line 1g standard-deduction add-back (skipped when the Step 2 box is checked).
STD_DEDUCTION_ADDBACK = {
    "married": Decimal("12900"),
    "single": Decimal("8600"),
    "head_of_household": Decimal("8600"),
}

# IRS 2026 annual percentage-method rows: (lower bound, base tax, rate).
# Preserve the published base tax: rounded checkbox boundaries cannot be
# integrated from marginal rates without introducing cent differences.
# Source: https://www.irs.gov/publications/p15t (Worksheet 1A and section 1).
_STANDARD = {
    "single": [
        (Decimal("0"), Decimal("0.00"), Decimal("0.0")),
        (Decimal("7500"), Decimal("0.00"), Decimal("0.1")),
        (Decimal("19900"), Decimal("1240.00"), Decimal("0.12")),
        (Decimal("57900"), Decimal("5800.00"), Decimal("0.22")),
        (Decimal("113200"), Decimal("17966.00"), Decimal("0.24")),
        (Decimal("209275"), Decimal("41024.00"), Decimal("0.32")),
        (Decimal("263725"), Decimal("58448.00"), Decimal("0.35")),
        (Decimal("648100"), Decimal("192979.25"), Decimal("0.37")),
    ],
    "married": [
        (Decimal("0"), Decimal("0.00"), Decimal("0.0")),
        (Decimal("19300"), Decimal("0.00"), Decimal("0.1")),
        (Decimal("44100"), Decimal("2480.00"), Decimal("0.12")),
        (Decimal("120100"), Decimal("11600.00"), Decimal("0.22")),
        (Decimal("230700"), Decimal("35932.00"), Decimal("0.24")),
        (Decimal("422850"), Decimal("82048.00"), Decimal("0.32")),
        (Decimal("531750"), Decimal("116896.00"), Decimal("0.35")),
        (Decimal("788000"), Decimal("206583.50"), Decimal("0.37")),
    ],
    "head_of_household": [
        (Decimal("0"), Decimal("0.00"), Decimal("0.0")),
        (Decimal("15550"), Decimal("0.00"), Decimal("0.1")),
        (Decimal("33250"), Decimal("1770.00"), Decimal("0.12")),
        (Decimal("83000"), Decimal("7740.00"), Decimal("0.22")),
        (Decimal("121250"), Decimal("16155.00"), Decimal("0.24")),
        (Decimal("217300"), Decimal("39207.00"), Decimal("0.32")),
        (Decimal("271750"), Decimal("56631.00"), Decimal("0.35")),
        (Decimal("656150"), Decimal("191171.00"), Decimal("0.37")),
    ],
}

_CHECKBOX = {
    "single": [
        (Decimal("0"), Decimal("0.00"), Decimal("0.0")),
        (Decimal("8050"), Decimal("0.00"), Decimal("0.1")),
        (Decimal("14250"), Decimal("620.00"), Decimal("0.12")),
        (Decimal("33250"), Decimal("2900.00"), Decimal("0.22")),
        (Decimal("60900"), Decimal("8983.00"), Decimal("0.24")),
        (Decimal("108938"), Decimal("20512.00"), Decimal("0.32")),
        (Decimal("136163"), Decimal("29224.00"), Decimal("0.35")),
        (Decimal("328350"), Decimal("96489.63"), Decimal("0.37")),
    ],
    "married": [
        (Decimal("0"), Decimal("0.00"), Decimal("0.0")),
        (Decimal("16100"), Decimal("0.00"), Decimal("0.1")),
        (Decimal("28500"), Decimal("1240.00"), Decimal("0.12")),
        (Decimal("66500"), Decimal("5800.00"), Decimal("0.22")),
        (Decimal("121800"), Decimal("17966.00"), Decimal("0.24")),
        (Decimal("217875"), Decimal("41024.00"), Decimal("0.32")),
        (Decimal("272325"), Decimal("58448.00"), Decimal("0.35")),
        (Decimal("400450"), Decimal("103291.75"), Decimal("0.37")),
    ],
    "head_of_household": [
        (Decimal("0"), Decimal("0.00"), Decimal("0.0")),
        (Decimal("12075"), Decimal("0.00"), Decimal("0.1")),
        (Decimal("20925"), Decimal("885.00"), Decimal("0.12")),
        (Decimal("45800"), Decimal("3870.00"), Decimal("0.22")),
        (Decimal("64925"), Decimal("8077.50"), Decimal("0.24")),
        (Decimal("112950"), Decimal("19603.50"), Decimal("0.32")),
        (Decimal("140175"), Decimal("28315.50"), Decimal("0.35")),
        (Decimal("332375"), Decimal("95585.50"), Decimal("0.37")),
    ],
}

# Supplemental wage withholding (Pub 15 / Worksheet 4): flat 22%, or 37% on
# cumulative supplemental wages above $1M for the year.
SUPPLEMENTAL_RATE = Decimal("0.22")
SUPPLEMENTAL_HIGH_RATE = Decimal("0.37")
SUPPLEMENTAL_HIGH_THRESHOLD = Decimal("1000000")


def _tax_from_brackets(wage: Decimal, brackets) -> Decimal:
    """Apply the IRS row's base tax and marginal rate to adjusted annual wages."""
    if wage <= 0:
        return Decimal("0")
    for lower, base_tax, rate in reversed(brackets):
        if wage >= lower:
            return base_tax + (wage - lower) * rate
    return Decimal("0")


def federal_income_tax(
    taxable_wages: Decimal,
    pay_periods: int,
    filing_status: str = "single",
    multiple_jobs: bool = False,
    dependents_amount: Decimal = Decimal("0"),
    other_income_annual: Decimal = Decimal("0"),
    deductions_annual: Decimal = Decimal("0"),
    extra_withholding: Decimal = Decimal("0"),
) -> Decimal:
    """Federal income tax to withhold for one pay period — Pub 15-T Worksheet 1A.

    `taxable_wages` is gross for the period already net of any pre-tax
    deductions that reduce federal taxable wages.
    """
    taxable_wages = Decimal(str(taxable_wages))
    if taxable_wages <= 0:
        return Decimal("0")
    fs = filing_status if filing_status in _STANDARD else "single"

    # Step 1 — adjusted annual wage amount
    annual_wage = taxable_wages * pay_periods
    line_1e = annual_wage + Decimal(str(other_income_annual))
    addback = Decimal("0") if multiple_jobs else STD_DEDUCTION_ADDBACK[fs]
    line_1h = Decimal(str(deductions_annual)) + addback
    adjusted_annual = line_1e - line_1h
    if adjusted_annual < 0:
        adjusted_annual = Decimal("0")

    # Step 2 — tentative withholding from the percentage-method schedule
    table = _CHECKBOX[fs] if multiple_jobs else _STANDARD[fs]
    tentative_annual = _tax_from_brackets(adjusted_annual, table)
    tentative_period = tentative_annual / pay_periods

    # Step 3 — apply the Step 3 dependent/credit amount
    credit_period = Decimal(str(dependents_amount)) / pay_periods
    withholding = tentative_period - credit_period
    if withholding < 0:
        withholding = Decimal("0")

    # Step 4 — add any extra per-period withholding from Step 4(c)
    withholding += Decimal(str(extra_withholding))
    return _q(withholding)


def supplemental_federal_tax(
    amount: Decimal, ytd_supplemental: Decimal = Decimal("0")
) -> Decimal:
    """Flat-rate federal withholding on supplemental wages (bonuses, etc.)."""
    amount = Decimal(str(amount))
    if amount <= 0:
        return Decimal("0")
    ytd = Decimal(str(ytd_supplemental))
    tax = Decimal("0")
    if ytd >= SUPPLEMENTAL_HIGH_THRESHOLD:
        tax = amount * SUPPLEMENTAL_HIGH_RATE
    elif ytd + amount > SUPPLEMENTAL_HIGH_THRESHOLD:
        over = ytd + amount - SUPPLEMENTAL_HIGH_THRESHOLD
        tax = (amount - over) * SUPPLEMENTAL_RATE + over * SUPPLEMENTAL_HIGH_RATE
    else:
        tax = amount * SUPPLEMENTAL_RATE
    return _q(tax)


def supplemental_aggregate_tax(
    supplemental: Decimal,
    regular_wages: Decimal,
    pay_periods: int,
    filing_status: str = "single",
    multiple_jobs: bool = False,
    dependents_amount: Decimal = Decimal("0"),
    other_income_annual: Decimal = Decimal("0"),
    deductions_annual: Decimal = Decimal("0"),
) -> Decimal:
    """Aggregate-method federal withholding on supplemental wages.

    Withhold the difference between the tax on (regular + supplemental) wages
    and the tax on the regular wages alone — the alternative to the flat 22%.
    """
    supplemental = Decimal(str(supplemental))
    regular_wages = Decimal(str(regular_wages))
    if supplemental <= 0:
        return Decimal("0")
    combined = federal_income_tax(
        regular_wages + supplemental,
        pay_periods,
        filing_status,
        multiple_jobs,
        dependents_amount,
        other_income_annual,
        deductions_annual,
    )
    base = federal_income_tax(
        regular_wages,
        pay_periods,
        filing_status,
        multiple_jobs,
        dependents_amount,
        other_income_annual,
        deductions_annual,
    )
    return _q(max(Decimal("0"), combined - base))


def _capped_wages(gross: Decimal, ytd_gross: Decimal, wage_base: Decimal) -> Decimal:
    """Portion of `gross` that is still below an annual wage-base cap."""
    if ytd_gross >= wage_base:
        return Decimal("0")
    if ytd_gross + gross > wage_base:
        return wage_base - ytd_gross
    return gross


def social_security(gross: Decimal, ytd_gross: Decimal = Decimal("0")) -> tuple:
    """Return (employee_ss, employer_ss) honouring the annual wage-base cap."""
    taxable = _capped_wages(Decimal(str(gross)), Decimal(str(ytd_gross)), SS_WAGE_BASE)
    amt = _q(taxable * SS_RATE)
    return amt, amt


def medicare(gross: Decimal, ytd_gross: Decimal = Decimal("0")) -> tuple:
    """Return (employee_medicare, employer_medicare).

    Employee Medicare includes the Additional Medicare Tax (0.9%) on wages
    above $200,000; the employer share never includes the additional tax.
    """
    gross = Decimal(str(gross))
    ytd_gross = Decimal(str(ytd_gross))
    base = _q(gross * MEDICARE_RATE)
    employee = base
    annual = ytd_gross + gross
    if annual > MEDICARE_ADDITIONAL_THRESHOLD:
        if ytd_gross >= MEDICARE_ADDITIONAL_THRESHOLD:
            extra_wages = gross
        else:
            extra_wages = annual - MEDICARE_ADDITIONAL_THRESHOLD
        employee += _q(extra_wages * MEDICARE_ADDITIONAL_RATE)
    return employee, base


def futa(gross: Decimal, ytd_gross: Decimal = Decimal("0")) -> Decimal:
    """Employer FUTA tax (effective 0.6% on the first $7,000 of wages)."""
    taxable = _capped_wages(
        Decimal(str(gross)), Decimal(str(ytd_gross)), FUTA_WAGE_BASE
    )
    return _q(taxable * FUTA_EFFECTIVE_RATE)


def suta(
    gross: Decimal, ytd_gross: Decimal, rate: Decimal, wage_base: Decimal
) -> Decimal:
    """Employer state unemployment tax on wages below the state wage base."""
    taxable = _capped_wages(
        Decimal(str(gross)), Decimal(str(ytd_gross)), Decimal(str(wage_base))
    )
    return _q(taxable * Decimal(str(rate)))


def resolve_suta_rate(explicit=None, work_state: str = None) -> Decimal:
    """Pick the SUTA rate to apply for one stub, most specific source first.

    1. An explicit per-pay-run rate passed by the caller.
    2. SUTA_RATE_BY_STATE — the experience rate the state assigned this
       employer. Multi-state employers have a different one in each state.
    3. SUTA_RATE, when the stub is in the employer's own state. This is the
       single-state setting that predates per-state rates, and an operator who
       set it means it for their home state — a published new-employer rate
       must not quietly override the real experience rate they entered.
    4. The state's new-employer rate from its tax table. Reached only for a
       state the operator never configured, where a state-specific published
       rate beats applying the home state's rate to wages earned elsewhere.
    5. SUTA_RATE, for a state with no table at all.
    """
    if explicit is not None:
        return Decimal(str(explicit))

    from app.config import EMPLOYER_STATE, SUTA_RATE, SUTA_RATE_BY_STATE
    from app.services.state_tax import suta_rate_for

    state = (work_state or "").strip().upper()

    configured = suta_rate_for(state, SUTA_RATE_BY_STATE, tables=False)
    if configured is not None:
        return configured

    if not state or state == (EMPLOYER_STATE or "").strip().upper():
        return Decimal(str(SUTA_RATE))

    from_table = suta_rate_for(state, None)
    if from_table is not None:
        return from_table
    return Decimal(str(SUTA_RATE))


def calculate_withholdings(
    gross_pay,
    *,
    pay_frequency="biweekly",
    filing_status: str = "single",
    multiple_jobs: bool = False,
    dependents_amount=Decimal("0"),
    other_income_annual=Decimal("0"),
    deductions_annual=Decimal("0"),
    extra_withholding=Decimal("0"),
    ytd_gross=Decimal("0"),
    ytd_fica=None,
    tips=Decimal("0"),
    ytd_tips=Decimal("0"),
    work_state: str = "WA",
    withholding_state: str = None,
    work_locality: str = None,
    residence_locality: str = None,
    wc_class_code: str = None,
    hours=Decimal("0"),
    pretax_deductions=Decimal("0"),
    pretax_fica=Decimal("0"),
    pretax_state=None,
    taxable_employer=Decimal("0"),
    supplemental: bool = False,
    supplemental_method: str = "flat",
    regular_wages=Decimal("0"),
    ytd_supplemental=Decimal("0"),
    suta_rate: Decimal = None,
    state_allowances: int = 0,
    state_extra_withholding=Decimal("0"),
    state_rate_override=None,
    local_tax_rate=None,
) -> dict:
    """Compute a full set of payroll taxes for one employee for one pay period.

    ``pretax_deductions`` is the total of pre-tax deductions that reduce
    federal income-tax wages; ``pretax_fica`` is the subset of those that
    ALSO reduce FICA wages (Section 125 cafeteria plans, HSA) — a
    traditional 401(k) reduces income tax but not FICA, so it belongs only
    in pretax_deductions. ``pretax_state`` is the amount that reduces STATE
    income-tax wages (None = same as federal); the benefits engine tracks
    the three bases separately because a code can reduce any combination.

    Returns employee-side withholding, employer-side taxes, the per-state
    results, and an itemized ``detail`` map for pay-stub / form rendering.
    ``tips`` and ``ytd_tips`` remain in federal/FICA wages but are excluded
    from Washington Paid Leave and WA Cares premium wages.
    ``ytd_fica`` is uncapped prior taxable FICA/FUTA wages reconstructed
    from paid benefit snapshots. None preserves the gross basis for callers
    without historical snapshots; total pre-tax deductions are not a proxy.
    ``taxable_employer`` is the separately valued noncash employer contribution
    explicitly classified as taxable in all modeled wage bases. It increases
    compensation for taxes, never cash gross or take-home pay.
    """
    gross = _q(gross_pay)
    fringe = Decimal(str(taxable_employer))
    if not fringe.is_finite() or fringe < 0:
        raise ValueError(
            "Taxable employer contributions must be finite and nonnegative"
        )
    fringe = _q(fringe)
    tax_gross = gross + fringe
    ytd = Decimal(str(ytd_gross))
    fica_ytd = ytd if ytd_fica is None else Decimal(str(ytd_fica))
    pretax = Decimal(str(pretax_deductions))
    pretax_fica_amt = Decimal(str(pretax_fica))
    pretax_state_amt = pretax if pretax_state is None else Decimal(str(pretax_state))
    pay_periods = periods_per_year(pay_frequency)

    if tax_gross <= 0:
        zero = Decimal("0")
        return {
            "gross": zero,
            "federal": zero,
            "ss": zero,
            "medicare": zero,
            "state_income": zero,
            "state_other_employee": zero,
            "local_tax": zero,
            "local_tax_employer": zero,
            "unknown_localities": [],
            "employer_ss": zero,
            "employer_medicare": zero,
            "futa": zero,
            "suta": zero,
            "state_other_employer": zero,
            "total_employee_tax": zero,
            "total_employer_tax": zero,
            "net": zero,
            "detail": {},
        }

    # Income-tax wages drop the full pre-tax total; FICA wages drop only the
    # cafeteria-plan / HSA subset.
    fed_taxable = max(Decimal("0"), tax_gross - pretax)
    state_taxable = max(Decimal("0"), tax_gross - pretax_state_amt)
    fica_wages = max(Decimal("0"), tax_gross - pretax_fica_amt)

    # --- Federal income tax ---
    if supplemental:
        if supplemental_method == "aggregate":
            federal = supplemental_aggregate_tax(
                fed_taxable,
                regular_wages,
                pay_periods,
                filing_status,
                multiple_jobs,
                dependents_amount,
                other_income_annual,
                deductions_annual,
            )
        else:
            # YTD supplemental wages drive the $1M/37% mandatory-flat-rate
            # tier — without them the high-earner rate can never fire.
            federal = supplemental_federal_tax(fed_taxable, ytd_supplemental)
    else:
        federal = federal_income_tax(
            fed_taxable,
            pay_periods,
            filing_status,
            multiple_jobs,
            dependents_amount,
            other_income_annual,
            deductions_annual,
            extra_withholding,
        )

    # --- FICA (on FICA wages — Section 125 / HSA reduce these) ---
    ss_emp, ss_empr = social_security(fica_wages, fica_ytd)
    med_emp, med_empr = medicare(fica_wages, fica_ytd)

    # --- Employer unemployment taxes ---
    futa_tax = futa(fica_wages, fica_ytd)

    # --- State engine ---
    # The work-state engine drives SUTA situs and state disability/leave
    # premiums; income tax may instead follow the residence state under a
    # reciprocity agreement (see state_tax.reciprocity).
    state_kw = dict(
        fica_wages=fica_wages,
        ytd_fica_wages=fica_ytd,
        tips=Decimal(str(tips)),
        ytd_tips=Decimal(str(ytd_tips)),
        state_allowances=state_allowances,
        state_extra_withholding=state_extra_withholding,
        state_rate_override=state_rate_override,
        local_tax_rate=local_tax_rate,
    )
    engine = get_engine(work_state)
    state = engine.calculate(
        gross=tax_gross,
        taxable=state_taxable,
        ytd_gross=ytd,
        pay_periods=pay_periods,
        hours=Decimal(str(hours)),
        filing_status=filing_status,
        wc_class_code=wc_class_code,
        **state_kw,
    )

    state_income = state.income_tax
    if (
        withholding_state
        and (work_state or "").strip().upper() != withholding_state.strip().upper()
    ):
        wh = get_engine(withholding_state).calculate(
            gross=tax_gross,
            taxable=state_taxable,
            ytd_gross=ytd,
            pay_periods=pay_periods,
            hours=Decimal(str(hours)),
            filing_status=filing_status,
            wc_class_code=wc_class_code,
            **state_kw,
        )
        state_income = wh.income_tax
        # the reciprocity state's income tax replaces the work state's, and
        # its detail line should say so on the stub
        for k in list(state.detail):
            if k.endswith("income tax") and not k.endswith("local income tax"):
                state.detail.pop(k)
        for k, v in wh.detail.items():
            if k.endswith("income tax") and not k.endswith("local income tax"):
                state.detail[k] = v

    # SUTA follows the WORK state — reciprocity moves income tax to the
    # residence state but never unemployment tax.
    rate = resolve_suta_rate(suta_rate, work_state)
    suta_tax = suta(fica_wages, fica_ytd, rate, engine.suta_wage_base)

    # --- Local / municipal taxes (the layer below the state) ---
    from app.services.local_tax import calculate_local_taxes

    local = calculate_local_taxes(
        work_locality=work_locality,
        residence_locality=residence_locality,
        taxable=fed_taxable,
        pay_periods=pay_periods,
        filing_status=filing_status,
        state_income_tax=state_income,
    )

    total_employee = (
        federal
        + state_income
        + state.employee_other
        + local.employee
        + ss_emp
        + med_emp
    )
    total_employer = (
        ss_empr + med_empr + futa_tax + suta_tax + state.employer_other + local.employer
    )
    net = gross - total_employee - pretax

    detail = {
        "federal_income_tax": federal,
        "social_security_employee": ss_emp,
        "medicare_employee": med_emp,
        "state_income_tax": state_income,
        "pretax_deductions": _q(pretax),
        "employer_social_security": ss_empr,
        "employer_medicare": med_empr,
        "futa": futa_tax,
        "suta": suta_tax,
        "employer_suta_wages": _q(
            _capped_wages(fica_wages, fica_ytd, engine.suta_wage_base)
        ),
    }
    detail.update(state.detail)
    if fringe:
        detail["taxable_employer_benefits"] = fringe
    detail["state_income_tax"] = state_income
    detail.update(local.detail)
    if local.employee or local.employer:
        detail["local_tax_total"] = local.employee

    return {
        "gross": gross,
        "federal": federal,
        "ss": ss_emp,
        "medicare": med_emp,
        "state_income": state_income,
        "state_other_employee": state.employee_other,
        "local_tax": local.employee,
        "local_tax_employer": local.employer,
        "unknown_localities": local.unknown,
        "employer_ss": ss_empr,
        "employer_medicare": med_empr,
        "futa": futa_tax,
        "suta": suta_tax,
        "state_other_employer": state.employer_other,
        "total_employee_tax": _q(total_employee),
        "total_employer_tax": _q(total_employer),
        "net": _q(net),
        "detail": detail,
    }
