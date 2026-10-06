"""Reconstruct taxable wages from a paycheck's immutable benefit snapshots.

Current benefit-code settings never describe a previously paid check. Legacy
or imported checks without snapshots retain their stored aggregate federal
deduction and gross FICA basis; their missing exclusions cannot be inferred.
"""

import json
from decimal import Decimal, InvalidOperation


def taxable_employer_wages(stub) -> Decimal:
    """Only explicitly calculated noncash contributions enter historical wages.

    The old employer_taxable flag also described special fringes such as GTL.
    It cannot reconstruct taxable compensation on pre-classification checks.
    """
    total = Decimal("0")
    for benefit in getattr(stub, "benefits", ()):
        try:
            rule = json.loads(getattr(benefit, "rule_json", None) or "{}")
        except (TypeError, ValueError):
            continue
        if (
            not isinstance(rule, dict)
            or rule.get("employer_tax_treatment") != "fully_taxable"
        ):
            continue
        if "taxable_employer_amount" not in rule:
            continue
        try:
            amount = Decimal(str(rule["taxable_employer_amount"]))
            employer_amount = Decimal(str(benefit.employer_amount or 0))
        except InvalidOperation:  # null or garbled: not a ValueError by itself
            raise ValueError("Invalid immutable taxable employer contribution")
        if not amount.is_finite() or amount < 0 or amount > employer_amount:
            raise ValueError("Invalid immutable taxable employer contribution")
        total += amount
    return total


def gross_wages(stub) -> Decimal:
    """Cash/tip gross plus explicitly recorded taxable noncash contributions."""
    return Decimal(str(stub.gross_pay or 0)) + taxable_employer_wages(stub)


def fica_wages(stub) -> Decimal:
    """Uncapped Social Security, Medicare and FUTA wages, including tips.

    Qualified cafeteria-plan/HSA employee deductions reduce these wages;
    traditional 401(k) deferrals and income-only ad-hoc deductions do not.
    """
    excluded = sum(
        (
            Decimal(str(benefit.employee_amount or 0))
            for benefit in stub.benefits
            if benefit.category == "pretax" and benefit.reduces_fica
        ),
        Decimal("0"),
    )
    return max(Decimal("0"), gross_wages(stub) - excluded)


def federal_wages(stub) -> Decimal:
    """Federal wages preserve income-only ad-hoc and legacy deductions.

    The aggregate deduction also contains snapshot amounts reducing only
    state or FICA wages. Restore those amounts to the federal wage base.
    """
    return _income_wages(stub, "reduces_federal")


def state_wages(stub) -> Decimal:
    """State income-tax wages using the paycheck's stored treatment flags."""
    return _income_wages(stub, "reduces_state")


def _income_wages(stub, flag: str) -> Decimal:
    nonreducing = sum(
        (
            Decimal(str(benefit.employee_amount or 0))
            for benefit in stub.benefits
            if benefit.category == "pretax" and not getattr(benefit, flag)
        ),
        Decimal("0"),
    )
    excluded = max(
        Decimal("0"), Decimal(str(stub.pretax_deductions or 0)) - nonreducing
    )
    return max(Decimal("0"), gross_wages(stub) - excluded)


def social_security_wage_parts(stub, ytd_fica: Decimal, wage_base: Decimal) -> tuple:
    """Split this check's capped Social Security wages and taxable tips.

    Call in pay-date/id order. Earlier taxable tips consume the same annual
    cap as regular wages and remain separately reportable on W-2 and 941.
    """
    wages = fica_wages(stub)
    tips = min(
        wages,
        max(
            Decimal("0"),
            Decimal(str(stub.reported_tips or 0))
            + Decimal(str(stub.paycheck_tips or 0)),
        ),
    )
    available = max(Decimal("0"), wage_base - ytd_fica)
    regular = min(wages - tips, available)
    taxable_tips = min(tips, available - regular)
    return regular, taxable_tips
