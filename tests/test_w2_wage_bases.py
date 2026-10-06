"""IRS 2026 wage-box rules using posted benefit and tip snapshots.

Primary references: irs.gov/instructions/iw2w3 (boxes 1, 3, 5, 7) and
ssa.gov/employer/efw/26efw2.pdf (RW 254-264 and RT 100-114).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.benefits import BenefitCode, PayStubBenefit
from app.models.payroll import Employee, PayRun, PayRunStatus, PayStub
from app.services.tax_forms import w2_w3
from app.services.tax_forms.form_940 import compute_940
from app.services.tax_forms.form_941 import compute_941
from app.services.tax_forms.efw2 import generate_efw2


def _stub(db, employee, pay_date, gross, pretax="0", tips=("0", "0")):
    run = PayRun(
        period_start=pay_date,
        period_end=pay_date,
        pay_date=pay_date,
        status=PayRunStatus.PROCESSED,
    )
    stub = PayStub(
        pay_run=run,
        employee=employee,
        gross_pay=Decimal(gross),
        pretax_deductions=Decimal(pretax),
        reported_tips=Decimal(tips[0]),
        paycheck_tips=Decimal(tips[1]),
    )
    db.add(stub)
    db.flush()
    return stub


def _benefit(db, stub, code, amount, *, federal=True, fica=False, employer="0"):
    snapshot = PayStubBenefit(
        pay_stub=stub,
        code=code,
        name=code,
        kind="both",
        category="pretax",
        calc_method="fixed_amount",
        employee_amount=Decimal(amount),
        employer_amount=Decimal(employer),
        reduces_federal=federal,
        reduces_state=True,
        reduces_fica=fica,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


@pytest.fixture
def employee(db_session):
    employee = Employee(first_name="Wage", last_name="Snapshot")
    db_session.add(employee)
    db_session.flush()
    return employee


def test_w2_uses_each_benefit_tax_flag_and_preserves_adhoc_deductions(
    db_session, employee
):
    stub = _stub(db_session, employee, date(2026, 1, 16), "10000", "2000")
    retirement = _benefit(db_session, stub, "401K", "1000", employer="1000")
    _benefit(db_session, stub, "SECTION125", "500", fica=True)
    _benefit(db_session, stub, "STATE_ONLY", "200", federal=False)
    # A current code edit cannot change the tax treatment already posted.
    current_code = BenefitCode(
        code="401K",
        name="Edited retirement rule",
        kind="deduction",
        category="pretax",
        calc_method="fixed_amount",
        reduces_federal=False,
        reduces_fica=True,
    )
    db_session.add(current_code)
    retirement.benefit_code = current_code
    db_session.flush()
    # Remaining $300 of stored pretax deductions is an ad-hoc income-only
    # deduction. Employer contributions never reduce the employee's wages.
    result = w2_w3.compute_w2(db_session, 2026, employee.id)
    assert result["box1_federal_wages"] == Decimal("8200.00")
    assert result["box16_state_wages"] == Decimal("8000.00")
    assert result["box3_ss_wages"] == Decimal("9500.00")
    assert result["box5_medicare_wages"] == Decimal("9500.00")


@pytest.fixture
def capped_tipped_employee(db_session, employee):
    prior = _stub(db_session, employee, date(2026, 1, 16), "180000", "10000")
    _benefit(db_session, prior, "SECTION125", "10000", fica=True)
    current = _stub(
        db_session,
        employee,
        date(2026, 2, 13),
        "20000",
        "5000",
        tips=("4000", "3000"),
    )
    _benefit(db_session, current, "HSA", "5000", fica=True)
    # Draft and void records must not consume the annual cap or add tips.
    excluded = _stub(
        db_session, employee, date(2026, 1, 1), "10000", tips=("1000", "0")
    )
    excluded.pay_run.status = PayRunStatus.VOID
    draft = _stub(db_session, employee, date(2026, 1, 2), "10000")
    draft.pay_run.status = PayRunStatus.DRAFT
    db_session.flush()
    return employee


def test_w2_separates_both_tip_types_and_shares_the_social_security_cap(
    db_session, capped_tipped_employee
):
    result = w2_w3.compute_w2(db_session, 2026, capped_tipped_employee.id)
    assert result["box1_federal_wages"] == Decimal("185000.00")
    assert result["box3_ss_wages"] == Decimal("178000.00")
    assert result["box7_ss_tips"] == Decimal("6500.00")
    assert result["box5_medicare_wages"] == Decimal("185000.00")
    assert result["box3_ss_wages"] + result["box7_ss_tips"] == Decimal("184500.00")


def test_earlier_taxable_tips_are_not_reclassified_as_later_regular_wages(
    db_session, employee
):
    # Query insertion order is deliberately opposite to payment order.
    _stub(db_session, employee, date(2026, 12, 18), "180000")
    _stub(db_session, employee, date(2026, 1, 16), "10000", tips=("4000", "1000"))
    result = w2_w3.compute_w2(db_session, 2026, employee.id)
    assert result["box3_ss_wages"] == Decimal("179500.00")
    assert result["box7_ss_tips"] == Decimal("5000.00")
    assert result["box5_medicare_wages"] == Decimal("190000.00")
    q1 = compute_941(db_session, 2026, 1)
    q4 = compute_941(db_session, 2026, 4)
    assert q1["social_security_wages"] == Decimal("5000.00")
    assert q1["social_security_tips"] == Decimal("5000.00")
    assert q4["social_security_wages"] == Decimal("174500.00")
    assert q4["social_security_tips"] == Decimal("0.00")


def test_legacy_without_benefit_snapshots_keeps_income_only_deduction_policy(
    db_session, employee
):
    _stub(db_session, employee, date(2026, 1, 16), "10000", "1000")
    result = w2_w3.compute_w2(db_session, 2026, employee.id)
    assert result["box1_federal_wages"] == Decimal("9000.00")
    assert result["box3_ss_wages"] == Decimal("10000.00")
    assert result["box5_medicare_wages"] == Decimal("10000.00")


def test_w2_w3_json_pdf_and_efw2_preserve_the_tip_box(
    client, db_session, capped_tipped_employee, monkeypatch
):
    employee_id = capped_tipped_employee.id
    w3 = w2_w3.compute_w3(db_session, 2026)
    assert w3["box7_ss_tips"] == Decimal("6500.00")
    assert (
        client.post(f"/api/payroll/forms/w2/{employee_id}?year=2026").json()["box_7"]
        == "6500.00"
    )
    assert client.post("/api/payroll/forms/w3/2026").json()["box_7"] == "6500.00"

    monkeypatch.setattr(w2_w3, "render_pdf", lambda html, **kwargs: html.encode())
    for html in (
        w2_w3.generate_w2_pdf(db_session, 2026, employee_id, {}),
        w2_w3.generate_w3_pdf(db_session, 2026, {}),
    ):
        assert b"Box 7" in html
        assert b"$6,500.00" in html

    content, _ = generate_efw2(db_session, 2026, {"name": "QA", "ein": "91-1234567"})
    records = content.split("\r\n")
    rw = next(record for record in records if record.startswith("RW"))
    rt = next(record for record in records if record.startswith("RT"))
    assert rw[253:264] == "00000650000"
    assert rt[99:114] == "000000000650000"


def test_941_advances_social_security_base_by_prior_taxable_wages(db_session, employee):
    prior = _stub(db_session, employee, date(2026, 1, 16), "180000", "15000")
    _benefit(db_session, prior, "SECTION125", "15000", fica=True)
    _stub(db_session, employee, date(2026, 4, 17), "10000")
    assert compute_941(db_session, 2026, 1)["total_wages"] == Decimal("165000.00")
    q2 = compute_941(db_session, 2026, 2)
    assert q2["social_security_wages"] == Decimal("10000.00")
    assert q2["additional_medicare_wages"] == Decimal("0.00")


def test_941_additional_medicare_uses_prior_taxable_wages(db_session, employee):
    prior = _stub(db_session, employee, date(2026, 1, 16), "205000", "20000")
    _benefit(db_session, prior, "HSA", "20000", fica=True)
    _stub(db_session, employee, date(2026, 4, 17), "10000")
    q2 = compute_941(db_session, 2026, 2)
    assert q2["medicare_wages"] == Decimal("10000.00")
    assert q2["additional_medicare_wages"] == Decimal("0.00")


def test_940_separates_benefit_exemptions_from_over_cap_payments(db_session, employee):
    prior = _stub(db_session, employee, date(2026, 1, 16), "7500", "2000")
    _benefit(db_session, prior, "SECTION125", "2000", fica=True)
    _stub(db_session, employee, date(2026, 4, 17), "1000")
    result = compute_940(db_session, 2026)
    assert result["total_payments"] == Decimal("8500.00")
    assert result["exempt_payments"] == Decimal("2000.00")
    assert result["excess_payments"] == Decimal("0.00")
    assert result["futa_taxable_wages"] == Decimal("6500.00")


def test_940_applies_cap_after_benefit_exemptions_and_preserves_recorded_tax(
    db_session, employee
):
    prior = _stub(db_session, employee, date(2026, 1, 16), "7500", "2000")
    _benefit(db_session, prior, "SECTION125", "2000", fica=True)
    current = _stub(db_session, employee, date(2026, 4, 17), "3500")
    # Historical tax is a recorded fact; reconstructing wages must not
    # rewrite tax actually posted, even when reconciliation is required.
    current.futa_tax = Decimal("9.00")
    db_session.flush()
    result = compute_940(db_session, 2026)
    assert result["total_payments"] == Decimal("11000.00")
    assert result["exempt_payments"] == Decimal("2000.00")
    assert result["excess_payments"] == Decimal("2000.00")
    assert result["futa_taxable_wages"] == Decimal("7000.00")
    assert result["total_futa_tax"] == Decimal("9.00")
    assert current.futa_tax == Decimal("9.00")


def test_941_tips_and_wages_match_w2_and_keep_shared_annual_cap(
    db_session, capped_tipped_employee
):
    q1 = compute_941(db_session, 2026, 1)
    assert q1["social_security_wages"] == Decimal("178000.00")
    assert q1["social_security_tips"] == Decimal("6500.00")
    assert q1["social_security_tax"] == Decimal("22072.00")
    assert q1["social_security_tip_tax"] == Decimal("806.00")
    assert q1["total_wages"] == Decimal("185000.00")
