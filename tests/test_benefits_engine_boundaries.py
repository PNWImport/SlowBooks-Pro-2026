"""Benefit calculation, effective-date and remittance boundary contracts."""

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace as Obj

import pytest

from app.models.benefits import (
    BenefitCode,
    BenefitRate,
    EmployeeBenefit,
    EmployeeGroup,
    EmployeeGroupBenefit,
    PayStubBenefit,
)
from app.models.payroll import Employee, PayRun, PayRunStatus, PayStub
from app.models.contacts import Vendor
from app.services import benefits_engine as engine

START = date(2026, 7, 1)
END = date(2026, 7, 14)


@pytest.mark.parametrize(
    "method,expected", [("amount_per_hour", "160"), ("tiered", "75"), ("unknown", "0")]
)
def test_additional_calculation_methods(method, expected):
    amount = engine._amount(
        method,
        D("2"),
        D("1000"),
        D("1000"),
        D("900"),
        D("80"),
        [{"up_to": 500, "rate": 5}, {"up_to": 1000, "rate": 10}],
    )
    assert amount == D(expected)


@pytest.mark.parametrize(
    "contribution,gross,limit,expected",
    [
        (0, 1000, None, 0),
        (100, 0, None, 0),
        (100, 1000, None, 50),
        (100, 1000, 3, 15),
    ],
)
def test_flat_employer_match_respects_contribution_and_wage_limit(
    contribution, gross, limit, expected
):
    assert engine._match(D(contribution), D(gross), D(50), limit, []) == D(expected)


def test_bad_tier_data_falls_back_without_interpreting_an_object():
    assert engine._d(None) == 0
    for value in ("{", '{"rate": 100}'):
        assert engine._tiers(BenefitRate(tiers_json=value)) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("effective_from", date(2026, 7, 15)),
        ("effective_to", date(2026, 6, 30)),
    ],
)
def test_code_outside_period_does_not_apply(field, value):
    code = BenefitCode(code="OUT", name="Outside", is_active=True, **{field: value})
    assert not engine.code_in_force(code, START, END)


def test_resolution_excludes_expired_future_and_unrated_assignments(db_session):
    group = EmployeeGroup(name="Boundary group")
    emp = Employee(first_name="Boundary", last_name="Benefits", employee_group=group)
    db_session.add(emp)
    db_session.flush()
    for i, dates in enumerate(
        ({"start_date": date(2026, 7, 15)}, {"end_date": date(2026, 6, 30)})
    ):
        code = BenefitCode(code=f"DATE{i}", name="Dated")
        db_session.add(code)
        db_session.flush()
        db_session.add(
            EmployeeBenefit(employee_id=emp.id, benefit_code_id=code.id, **dates)
        )
    for name, active in (("INACTIVE", False), ("UNRATED", True)):
        code = BenefitCode(code=name, name=name, is_active=active)
        db_session.add(code)
        db_session.flush()
        db_session.add(EmployeeGroupBenefit(group_id=group.id, benefit_code_id=code.id))
    db_session.commit()
    assert engine.resolve_for_employee(db_session, emp, START, END) == []


def test_employer_annual_cap_uses_existing_ytd(db_session, monkeypatch):
    emp = Employee(first_name="Cap", last_name="Test")
    code = BenefitCode(
        code="CAP", name="Cap", kind="benefit", calc_method="fixed_amount"
    )
    db_session.add_all([emp, code])
    db_session.commit()
    monkeypatch.setattr(
        engine, "get_ytd", lambda *args: Obj(employee_amount=0, employer_amount=D(95))
    )
    resolved = engine.Resolved(
        code=code,
        rate=BenefitRate(),
        source="assignment",
        employer_rate=D(20),
        employer_annual_cap=D(100),
    )
    result = engine.compute(
        db_session, emp, D(1000), D(80), START, END, 2026, resolved=[resolved]
    )
    assert result.employer_total == D("5.00")
    assert result.employee_total == 0


def test_unmapped_employer_expense_is_retained_for_fallback_posting():
    stub = Obj(
        benefits=[
            Obj(
                employee_amount=2,
                employer_amount=3,
                liability_account_id=None,
                expense_account_id=None,
            )
        ]
    )
    result = engine.gl_groups(Obj(stubs=[stub]))
    assert result.unmapped_liability == D(5)
    assert result.unmapped_expense == D(3)
    assert result.employee_total == D(2)
    assert result.employer_total == D(3)


def test_account_and_standard_code_seeding_are_idempotent(db_session):
    expected = {row[0] for row in engine.DEFAULT_ACCOUNTS}
    assert set(engine.ensure_accounts(db_session)) == expected
    assert engine.ensure_accounts(db_session) == []
    first = engine.seed_standard_codes(db_session)
    second = engine.seed_standard_codes(db_session)
    assert {c.id for c in first} == {c.id for c in second}
    assert db_session.query(BenefitCode).count() == len(engine.STANDARD_CODES)


def test_remittance_ignores_zero_rows_and_refuses_unmapped_bill(db_session):
    employee = Employee(first_name="Remit", last_name="Test")
    vendor = Vendor(name="Remittance vendor")
    run = PayRun(
        period_start=START, period_end=END, pay_date=END, status=PayRunStatus.PROCESSED
    )
    db_session.add_all([employee, vendor, run])
    db_session.flush()
    stub = PayStub(employee_id=employee.id, pay_run_id=run.id)
    db_session.add(stub)
    db_session.flush()
    snapshot = PayStubBenefit(
        pay_stub_id=stub.id,
        code="REMIT",
        name="Remit",
        kind="benefit",
        category="pretax",
        calc_method="fixed_amount",
        remittance_vendor_id=vendor.id,
        employee_amount=0,
        employer_amount=0,
    )
    db_session.add(snapshot)
    db_session.commit()
    assert engine.remittance_rows(db_session, START, END) == []
    snapshot.employer_amount = 20
    db_session.commit()
    with pytest.raises(ValueError, match="no liability account"):
        engine.create_remittance_bill(db_session, vendor.id, START, END)
