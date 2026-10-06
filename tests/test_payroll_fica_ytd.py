"""Qualified benefit exclusions must remain in cumulative FICA/FUTA wages.

IRS Pub 15/15-B excludes qualified Section 125/HSA amounts from Social
Security, Medicare and FUTA wages; traditional 401(k) deferrals remain in
these bases. Expected dollars use published 2026 rates and thresholds.
https://www.irs.gov/publications/p15
https://www.irs.gov/publications/p15b
https://www.irs.gov/businesses/small-businesses-self-employed/questions-and-answers-for-the-additional-medicare-tax
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.benefits import BenefitCode, PayStubBenefit
from app.models.payroll import PayRun, PayRunStatus, PayRunType, PayStub
from app.services.payroll_service import calculate_withholdings


@pytest.mark.parametrize(
    "prior_fica,field,expected",
    [
        ("184000", "ss", "31.00"),
        ("184500", "ss", "0.00"),
        ("185000", "ss", "0.00"),
        ("199500", "medicare", "16.65"),
        ("200000", "medicare", "21.15"),
        ("6500", "futa", "3.00"),
        ("7000", "futa", "0.00"),
        ("0", "ss", "55.80"),
    ],
)
def test_current_and_prior_qualified_wages_at_cap_boundaries(
    prior_fica, field, expected
):
    result = calculate_withholdings(
        Decimal("1000"),
        work_state="TX",
        ytd_gross=Decimal("250000"),
        ytd_fica=Decimal(prior_fica),
        pretax_fica=Decimal("100"),
    )
    assert result[field] == Decimal(expected)


@pytest.mark.parametrize(
    "status,paid,prior_gross,field,expected",
    [
        (PayRunStatus.PROCESSED, date(2026, 6, 20), "184000", "ss_tax", "31.00"),
        (PayRunStatus.PROCESSED, date(2026, 6, 20), "199500", "medicare_tax", "19.00"),
        (PayRunStatus.PROCESSED, date(2026, 6, 20), "6500", "futa_tax", "3.00"),
        (PayRunStatus.DRAFT, date(2026, 1, 15), "184500", "ss_tax", "62.00"),
        (PayRunStatus.DRAFT, date(2026, 1, 15), "205000", "medicare_tax", "14.50"),
        (PayRunStatus.DRAFT, date(2026, 1, 15), "7500", "futa_tax", "6.00"),
    ],
)
def test_paid_same_day_checks_count_but_unpaid_drafts_do_not(
    client, db_session, seed_accounts, status, paid, prior_gross, field, expected
):
    employee = _employee(client, rate=12.5)
    _prior(db_session, employee["id"], prior_gross, "0", status=status, paid=paid)
    stub = _regular(client, employee["id"])
    assert Decimal(str(stub[field])) == Decimal(expected)


def _employee(client, rate=125):
    response = client.post(
        "/api/employees",
        json={
            "first_name": "Qualified",
            "last_name": "Benefits",
            "pay_type": "hourly",
            "pay_rate": rate,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "TX",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _prior(
    db,
    employee_id,
    gross,
    excluded,
    *,
    reduces_fica=True,
    status=PayRunStatus.PROCESSED,
    paid=date(2026, 1, 15),
):
    code = BenefitCode(
        code=f"S125-{status.value}-{paid.month}",
        name="Qualified plan",
        kind="deduction",
        category="pretax",
        calc_method="fixed_amount",
        reduces_federal=True,
        reduces_state=True,
        reduces_fica=reduces_fica,
    )
    run = PayRun(
        period_start=paid,
        period_end=paid,
        pay_date=paid,
        status=status,
        run_type=PayRunType.OFF_CYCLE,
    )
    db.add_all([code, run])
    db.flush()
    stub = PayStub(
        employee_id=employee_id,
        pay_run_id=run.id,
        gross_pay=Decimal(gross),
        pretax_deductions=Decimal(excluded),
        net_pay=0,
    )
    db.add(stub)
    db.flush()
    db.add(
        PayStubBenefit(
            pay_stub_id=stub.id,
            benefit_code_id=code.id,
            code=code.code,
            name=code.name,
            kind="deduction",
            category="pretax",
            calc_method="fixed_amount",
            reduces_federal=True,
            reduces_state=True,
            reduces_fica=reduces_fica,
            employee_amount=Decimal(excluded),
        )
    )
    # A later plan edit must never rewrite a processed check's tax treatment.
    code.reduces_fica = not reduces_fica
    db.commit()
    return stub


def _regular(client, employee_id, hours=80):
    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-06-01",
            "period_end": "2026-06-14",
            "pay_date": "2026-06-20",
            "stubs": [{"employee_id": employee_id, "hours": hours}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["stubs"][0]


@pytest.mark.parametrize(
    "prior_gross,excluded,rate,field,expected",
    [
        ("180000", "15000", 125, "ss_tax", "620.00"),
        ("205000", "20000", 125, "medicare_tax", "145.00"),
        ("7500", "2000", 12.5, "futa_tax", "6.00"),
    ],
)
def test_regular_tax_uses_processed_benefit_snapshots(
    client, db_session, seed_accounts, prior_gross, excluded, rate, field, expected
):
    employee = _employee(client, rate)
    prior = _prior(db_session, employee["id"], prior_gross, excluded)
    stub = _regular(client, employee["id"])
    assert Decimal(str(stub[field])) == Decimal(expected)
    assert prior.benefits[0].reduces_fica is True
    assert prior.benefits[0].benefit_code.reduces_fica is False
    if field == "ss_tax":
        assert Decimal(str(stub["employer_ss_tax"])) == Decimal("620.00")
    if field == "medicare_tax":
        assert Decimal(str(stub["employer_medicare_tax"])) == Decimal("145.00")


def test_retirement_deferrals_do_not_reduce_fica_ytd(client, db_session, seed_accounts):
    employee = _employee(client)
    _prior(db_session, employee["id"], "180000", "15000", reduces_fica=False)
    # A traditional 401(k) reduces income tax, never the FICA wage-base cap.
    stub = _regular(client, employee["id"])
    assert Decimal(str(stub["ss_tax"])) == Decimal("279.00")


@pytest.mark.parametrize("ignored", ["void", "future"])
def test_ytd_snapshot_exclusions_respect_voids_and_pay_date_cutoff(
    client, db_session, seed_accounts, ignored
):
    employee = _employee(client)
    _prior(db_session, employee["id"], "180000", "15000")
    _prior(
        db_session,
        employee["id"],
        "10000",
        "5000",
        status=PayRunStatus.VOID if ignored == "void" else PayRunStatus.PROCESSED,
        paid=date(2026, 12, 15) if ignored == "future" else date(2026, 2, 15),
    )
    stub = _regular(client, employee["id"])
    assert Decimal(str(stub["ss_tax"])) == Decimal("620.00")


def test_legacy_stub_without_benefit_snapshots_keeps_gross_fica_basis(
    client, db_session, seed_accounts
):
    employee = _employee(client)
    prior = _prior(db_session, employee["id"], "180000", "15000")
    for benefit in list(prior.benefits):
        db_session.delete(benefit)
    db_session.commit()
    db_session.expire(prior, ["benefits"])
    stub = _regular(client, employee["id"])
    assert Decimal(str(stub["ss_tax"])) == Decimal("279.00")


def test_gross_up_uses_qualified_historical_wages(client, db_session, monkeypatch):
    from app.routes.payroll import runs

    class PayrollDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 20)

    monkeypatch.setattr(runs, "date", PayrollDate)
    employee = _employee(client)
    _prior(db_session, employee["id"], "180000", "15000")
    response = client.post(
        "/api/payroll/gross-up",
        json={"employee_id": employee["id"], "target_net": 7000, "supplemental": True},
    )
    assert response.status_code == 200, response.text
    # 22% supplemental + 6.2% SS + 1.45% Medicare, all below taxable cap.
    assert (
        Decimal("9950.24")
        <= Decimal(str(response.json()["gross"]))
        <= Decimal("9950.26")
    )
    assert abs(Decimal(str(response.json()["net"])) - Decimal("7000")) <= Decimal(
        "0.01"
    )


def test_retro_pay_uses_qualified_historical_wages(client, db_session):
    employee = _employee(client)
    _prior(db_session, employee["id"], "180000", "15000")
    run = PayRun(
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 1),
        pay_date=date(2026, 3, 5),
        status=PayRunStatus.PROCESSED,
        run_type=PayRunType.REGULAR,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        PayStub(
            employee_id=employee["id"],
            pay_run_id=run.id,
            gross_pay=125,
            detail_json='{"_payroll_earnings":{"version":1,"source":"hourly","pay_frequency":"biweekly","prorated_salary":false}}',
            hours=1,
            regular_hours=1,
            net_pay=0,
        )
    )
    db_session.commit()
    response = client.post(
        "/api/payroll/retro-pay/apply",
        json={
            "employee_id": employee["id"],
            "new_rate": 10125,
            "effective_date": "2026-03-01",
            "pay_date": "2026-06-20",
        },
    )
    assert response.status_code == 201, response.text
    stub = (
        db_session.query(PayStub)
        .filter_by(pay_run_id=response.json()["pay_run_id"])
        .one()
    )
    assert stub.gross_pay == Decimal("10000.00")
    assert stub.ss_tax == Decimal("620.00")


def test_termination_payout_uses_qualified_historical_wages(client, db_session):
    from app.models.pto import AccrualMethod, PTOAccrual, PTOPolicy, PTOType

    employee = _employee(client)
    _prior(db_session, employee["id"], "180000", "15000")
    policy = PTOPolicy(
        name="Qualified benefits payout",
        pto_type=PTOType.VACATION,
        accrual_method=AccrualMethod.ANNUAL_GRANT,
        accrual_rate=80,
    )
    db_session.add(policy)
    db_session.flush()
    db_session.add(
        PTOAccrual(employee_id=employee["id"], policy_id=policy.id, balance=80)
    )
    db_session.commit()
    response = client.post(
        f"/api/employees/{employee['id']}/terminate",
        json={
            "termination_date": "2026-06-20",
            "reason": "involuntary",
            "payout_pto": True,
        },
    )
    assert response.status_code == 200, response.text
    stub = (
        db_session.query(PayStub)
        .filter_by(pay_run_id=response.json()["pto_payout_run_id"])
        .one()
    )
    assert stub.gross_pay == Decimal("10000.00")
    assert stub.ss_tax == Decimal("620.00")
