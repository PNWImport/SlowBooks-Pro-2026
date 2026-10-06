"""Independent 2026 Paid Leave Oregon contribution and wage-basis cases.

Official employee/employer examples use $1,000 subject wages -> $6/$4.
Tips remain subject; qualified Section 125 wages are excluded, while employee
retirement deferrals remain subject. Employer classification is the documented
standard large-employer mode, not inferred from the current employee roster.
https://paidleave.oregon.gov/employers/contributions-calculator.html
https://paidleave.oregon.gov/resources/
"""

from datetime import date
from decimal import Decimal
import json

import pytest

from app.services.payroll_service import calculate_withholdings
from app.services.state_tax.oregon import OregonEngine
from app.models.benefits import (
    BenefitCode,
    BenefitRate,
    EmployeeBenefit,
    PayStubBenefit,
)
from app.models.payroll import PayRun, PayRunStatus, PayStub


def _calculate(**overrides):
    args = {
        "gross": Decimal("1000"),
        "taxable": Decimal("1000"),
        "ytd_gross": Decimal("0"),
        "pay_periods": 26,
        "hours": Decimal("40"),
        "filing_status": "single",
        "wc_class_code": None,
    }
    args.update(overrides)
    return OregonEngine().calculate(**args)


def _assert_paid_leave(result, employee, employer):
    assert result.detail["OR Paid Leave (employee)"] == Decimal(employee)
    assert result.detail["OR Paid Leave (employer)"] == Decimal(employer)
    assert (
        result.employee_other
        == Decimal(employee) + result.detail["OR statewide transit tax"]
    )
    assert result.employer_other == Decimal(employer)


def test_standard_large_employer_matches_official_1000_dollar_example():
    result = _calculate()
    _assert_paid_leave(result, "6.00", "4.00")
    assert result.detail["OR statewide transit tax"] == Decimal("1.00")


def test_income_tax_retirement_deductions_do_not_reduce_paid_leave_wages():
    # $500 of traditional 401(k) deferrals reduce income-tax wages only.
    _assert_paid_leave(_calculate(taxable=Decimal("500")), "6.00", "4.00")


def test_reported_and_paycheck_tips_remain_paid_leave_wages():
    result = _calculate(
        gross=Decimal("1200"),
        taxable=Decimal("1200"),
        tips=Decimal("200"),
        ytd_tips=Decimal("10000"),
        fica_wages=Decimal("1200"),
        ytd_fica_wages=Decimal("0"),
    )
    _assert_paid_leave(result, "7.20", "4.80")


def test_section125_exclusions_use_supplied_subject_wages_not_income_tax_base():
    # Gross $1,000 less $250 qualified health/FSA/HSA and $100 retirement:
    # income-tax wages $650, subject wages $750, transit stays on gross.
    result = _calculate(
        taxable=Decimal("650"),
        fica_wages=Decimal("750"),
        ytd_fica_wages=Decimal("0"),
    )
    _assert_paid_leave(result, "4.50", "3.00")
    assert result.detail["OR statewide transit tax"] == Decimal("1.00")


def test_zero_supplied_subject_wages_do_not_fall_back_to_gross():
    _assert_paid_leave(
        _calculate(fica_wages=Decimal("0"), ytd_fica_wages=Decimal("0")),
        "0.00",
        "0.00",
    )


@pytest.mark.parametrize(
    "ytd,employee,employer",
    [
        ("184000", "3.00", "2.00"),
        ("184500", "0.00", "0.00"),
        ("200000", "0.00", "0.00"),
    ],
)
def test_2026_wage_cap_crossing_and_exhaustion(ytd, employee, employer):
    _assert_paid_leave(_calculate(ytd_gross=Decimal(ytd)), employee, employer)


def test_historical_section125_snapshot_wages_drive_the_annual_cap():
    result = _calculate(
        gross=Decimal("10000"),
        taxable=Decimal("9000"),
        ytd_gross=Decimal("180000"),
        fica_wages=Decimal("9750"),
        ytd_fica_wages=Decimal("165000"),
    )
    _assert_paid_leave(result, "58.50", "39.00")


def test_each_share_rounds_to_cents_at_a_partial_cap():
    _assert_paid_leave(_calculate(ytd_gross=Decimal("184499.15")), "0.01", "0.00")


def test_no_paid_leave_for_nonpositive_wages():
    for gross in [Decimal("0"), Decimal("-1")]:
        result = _calculate(gross=gross)
        assert result.employee_other == result.employer_other == 0


def test_full_calculator_forwards_current_and_historical_qualified_wages():
    result = calculate_withholdings(
        Decimal("1000"),
        work_state="OR",
        ytd_gross=Decimal("184500"),
        ytd_fica=Decimal("184000"),
        pretax_deductions=Decimal("400"),
        pretax_fica=Decimal("250"),
        tips=Decimal("100"),
    )
    # Historical qualified wages leave $500 of the annual base; current
    # subject wages $750 include tips and exceed that remaining base.
    assert result["detail"]["OR Paid Leave (employee)"] == Decimal("3.00")
    assert result["detail"]["OR Paid Leave (employer)"] == Decimal("2.00")
    assert result["state_other_employee"] == Decimal("4.00")
    assert result["state_other_employer"] == Decimal("2.00")


@pytest.mark.parametrize(
    "historical_exclusion,employee_share,employer_share",
    [(True, "58.50", "39.00"), (False, "27.00", "18.00")],
)
def test_payroll_route_uses_frozen_benefit_basis_and_keeps_tips(
    client,
    db_session,
    seed_accounts,
    historical_exclusion,
    employee_share,
    employer_share,
):
    response = client.post(
        "/api/employees",
        json={
            "first_name": "Paid Leave",
            "last_name": "Oregon",
            "pay_type": "hourly",
            "pay_rate": 122.5,
            "work_state": "OR",
            "pay_frequency": "biweekly",
            "filing_status": "single",
        },
    )
    assert response.status_code == 201, response.text
    employee_id = response.json()["id"]
    history_code = BenefitCode(
        code="OR-HISTORY",
        name="Historical benefit",
        kind="deduction",
        category="pretax",
        calc_method="fixed_amount",
        reduces_fica=historical_exclusion,
    )
    prior_run = PayRun(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 14),
        pay_date=date(2026, 1, 15),
        status=PayRunStatus.PROCESSED,
    )
    db_session.add_all([history_code, prior_run])
    db_session.flush()
    prior_stub = PayStub(
        employee_id=employee_id,
        pay_run_id=prior_run.id,
        gross_pay=Decimal("180000"),
        pretax_deductions=Decimal("15000"),
    )
    db_session.add(prior_stub)
    db_session.flush()
    db_session.add(
        PayStubBenefit(
            pay_stub_id=prior_stub.id,
            benefit_code_id=history_code.id,
            code=history_code.code,
            name=history_code.name,
            kind="deduction",
            category="pretax",
            calc_method="fixed_amount",
            reduces_fica=historical_exclusion,
            employee_amount=Decimal("15000"),
        )
    )
    # Editing the current code must not change the prior posted wage base.
    history_code.reduces_fica = not historical_exclusion
    for name, amount, excludes in [("OR-S125", "250", True), ("OR-401K", "750", False)]:
        code = BenefitCode(
            code=name,
            name=name,
            kind="deduction",
            category="pretax",
            calc_method="fixed_amount",
            reduces_federal=True,
            reduces_state=True,
            reduces_fica=excludes,
        )
        db_session.add(code)
        db_session.flush()
        db_session.add_all(
            [
                BenefitRate(
                    benefit_code_id=code.id,
                    effective_from=date(2026, 1, 1),
                    employee_rate=Decimal(amount),
                ),
                EmployeeBenefit(employee_id=employee_id, benefit_code_id=code.id),
            ]
        )
    db_session.commit()

    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-06-01",
            "period_end": "2026-06-14",
            "pay_date": "2026-06-20",
            "stubs": [
                {
                    "employee_id": employee_id,
                    "hours": 80,
                    "reported_tips": 100,
                    "paycheck_tips": 100,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    stub = response.json()["stubs"][0]
    assert Decimal(str(stub["gross_pay"])) == Decimal("10000.00")
    detail = json.loads(db_session.get(PayStub, stub["id"]).detail_json)
    assert Decimal(detail["OR Paid Leave (employee)"]) == Decimal(employee_share)
    assert Decimal(detail["OR Paid Leave (employer)"]) == Decimal(employer_share)
    assert Decimal(str(stub["state_other_employee"])) == Decimal(employee_share) + 10
    assert Decimal(str(stub["state_other_employer"])) == Decimal(employer_share)
