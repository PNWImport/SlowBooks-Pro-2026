"""Two independent database transactions cannot spend one wage allowance."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier, BrokenBarrierError

import pytest
from fastapi import HTTPException

from app.models.payroll import Employee, PayRun, PayRunStatus, PayStub
from app.models.transactions import Transaction
from app.models.benefits import BenefitCode, BenefitRate, BenefitYTD, EmployeeBenefit
from app.routes.payroll import runs
from app.schemas.payroll import PayRunCreate
from tests.conftest import seed_accounts
from tests.test_accounting_concurrency import (
    accounting_sessions as _accounting_sessions,
)


@pytest.fixture(params=["postgresql", "sqlite"])
def payroll_sessions(request, tmp_path):
    yield from _accounting_sessions.__wrapped__(request, tmp_path)


def _draft_request(employee_ids, paid=date(2026, 6, 20)):
    return PayRunCreate(
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 14),
        pay_date=paid,
        stubs=[
            {"employee_id": employee_id, "gross_override": "1000"}
            for employee_id in employee_ids
        ],
    )


def _seed(factory, employee_count=1):
    with factory() as db:
        seed_accounts.__wrapped__(db)
        employees = [
            Employee(
                first_name="Concurrent",
                last_name=str(i),
                pay_rate=12.5,
                work_state="TX",
            )
            for i in range(employee_count)
        ]
        db.add_all(employees)
        db.flush()
        prior = PayRun(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 15),
            pay_date=date(2026, 1, 16),
            status=PayRunStatus.PROCESSED,
        )
        db.add(prior)
        db.flush()
        db.add_all(
            [
                PayStub(
                    employee_id=employee.id,
                    pay_run_id=prior.id,
                    gross_pay=Decimal("184000"),
                )
                for employee in employees
            ]
        )
        db.commit()
        return [employee.id for employee in employees]


@pytest.mark.parametrize("second_day", [20, 27])
@pytest.mark.parametrize("employee_count", [1, 2])
def test_overlapping_drafts_process_once_per_history_even_with_reversed_roster(
    payroll_sessions, monkeypatch, second_day, employee_count
):
    factory = payroll_sessions
    ids = _seed(factory, employee_count)
    with factory() as db:
        first = runs.create_pay_run(_draft_request(ids), db).id
        second = runs.create_pay_run(
            _draft_request(ids[::-1], date(2026, 6, second_day)), db
        ).id
    start = Barrier(2)
    both_validated = Barrier(2)
    validate = runs.validate_draft_history

    def overlap_after_validation(db, run):
        validate(db, run)
        # Without the employee lock both drafts reach this point against
        # the same paid history before either posts. With the lock, the
        # first proceeds after timeout and the second observes its commit.
        try:
            both_validated.wait(timeout=1)
        except BrokenBarrierError:
            pass

    monkeypatch.setattr(runs, "validate_draft_history", overlap_after_validation)

    def process(run_id):
        with factory() as db:
            # Exercise refresh after another request commits, even when this
            # session already cached the run as DRAFT.
            assert db.get(PayRun, run_id).status == PayRunStatus.DRAFT
            start.wait(timeout=10)
            try:
                runs.process_pay_run(run_id, db)
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(process, run_id) for run_id in (first, second)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(results) == [200, 409]
    with factory() as db:
        paid = (
            db.query(PayRun)
            .filter(
                PayRun.id.in_([first, second]), PayRun.status == PayRunStatus.PROCESSED
            )
            .one()
        )
        held = (
            db.query(PayRun)
            .filter(PayRun.id.in_([first, second]), PayRun.status == PayRunStatus.DRAFT)
            .one()
        )
        assert held.transaction_id is None
        assert (
            sum((stub.ss_tax for stub in paid.stubs), Decimal("0"))
            == Decimal("31") * employee_count
        )
        assert db.query(Transaction).count() == 1


def test_two_requests_for_same_draft_do_not_post_twice(payroll_sessions):
    factory = payroll_sessions
    ids = _seed(factory)
    with factory() as db:
        run_id = runs.create_pay_run(_draft_request(ids), db).id
    start = Barrier(2)

    def process():
        with factory() as db:
            assert db.get(PayRun, run_id).status == PayRunStatus.DRAFT
            start.wait(timeout=10)
            try:
                runs.process_pay_run(run_id, db)
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(process) for _ in range(2)]
        assert sorted(future.result(timeout=30) for future in futures) == [200, 400]
    with factory() as db:
        assert db.query(Transaction).count() == 1


def _seed_loan(factory, employee_id):
    with factory() as db:
        code = BenefitCode(
            code="LOAN-RACE",
            name="Loan",
            kind="both",
            category="posttax",
            calc_method="fixed_amount",
            employer_calc_method="fixed_amount",
            tracks_balance=True,
        )
        db.add(code)
        db.flush()
        db.add(
            BenefitRate(
                benefit_code_id=code.id,
                effective_from=date(2026, 1, 1),
                employee_rate=100,
                employer_rate=50,
                annual_cap=150,
                employer_annual_cap=75,
            )
        )
        assignment = EmployeeBenefit(
            employee_id=employee_id, benefit_code_id=code.id, balance_remaining=150
        )
        db.add(assignment)
        db.commit()
        return code.id, assignment.id


def test_concurrent_staging_reserves_each_loan_dollar_once(payroll_sessions):
    factory = payroll_sessions
    ids = _seed(factory)
    code_id, assignment_id = _seed_loan(factory, ids[0])
    start = Barrier(2)

    def stage():
        with factory() as db:
            start.wait(timeout=10)
            return runs.create_pay_run(_draft_request(ids), db).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(stage) for _ in range(2)]
        run_ids = [future.result(timeout=30) for future in futures]
    with factory() as db:
        stubs = db.query(PayStub).filter(PayStub.pay_run_id.in_(run_ids)).all()
        assert sorted(stub.posttax_deductions for stub in stubs) == [
            Decimal("50"),
            Decimal("100"),
        ]
        assert sorted(stub.employer_benefits for stub in stubs) == [
            Decimal("25"),
            Decimal("50"),
        ]
        assert db.get(EmployeeBenefit, assignment_id).balance_remaining == 0
        ytd = db.query(BenefitYTD).filter_by(benefit_code_id=code_id).one()
        assert (ytd.employee_amount, ytd.employer_amount) == (
            Decimal("150"),
            Decimal("75"),
        )


@pytest.mark.parametrize("second_action", ["cancel", "process"])
def test_concurrent_cancel_never_double_refunds_or_cancels_paid_payroll(
    payroll_sessions, second_action
):
    factory = payroll_sessions
    ids = _seed(factory)
    code_id, assignment_id = _seed_loan(factory, ids[0])
    with factory() as db:
        run_id = runs.create_pay_run(_draft_request(ids), db).id
    start = Barrier(2)

    def mutate(action):
        with factory() as db:
            assert db.get(PayRun, run_id).status == PayRunStatus.DRAFT
            start.wait(timeout=10)
            try:
                (runs.cancel_pay_run if action == "cancel" else runs.process_pay_run)(
                    run_id, db
                )
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(mutate, action) for action in ("cancel", second_action)]
        results = [future.result(timeout=30) for future in futures]
    assert results.count(200) == 1
    assert next(status for status in results if status != 200) in (400, 409)
    with factory() as db:
        run = db.get(PayRun, run_id)
        ytd = db.query(BenefitYTD).filter_by(benefit_code_id=code_id).one()
        if run.status == PayRunStatus.VOID:
            assert db.get(EmployeeBenefit, assignment_id).balance_remaining == Decimal(
                "150"
            )
            assert (ytd.employee_amount, ytd.employer_amount) == (
                Decimal("0"),
                Decimal("0"),
            )
            assert run.transaction_id is None and db.query(Transaction).count() == 0
        else:
            assert run.status == PayRunStatus.PROCESSED
            assert db.get(EmployeeBenefit, assignment_id).balance_remaining == Decimal(
                "50"
            )
            assert (ytd.employee_amount, ytd.employer_amount) == (
                Decimal("100"),
                Decimal("50"),
            )
            assert db.query(Transaction).count() == 1


def test_concurrent_retro_applications_reserve_paid_source_once(
    payroll_sessions, monkeypatch
):
    from app.routes.payroll.retro import RetroPayRequest, retro_pay_apply
    from app.services import retro_pay

    factory = payroll_sessions
    with factory() as db:
        seed_accounts.__wrapped__(db)
        employee = Employee(
            first_name="Retro", last_name="Race", pay_rate=20, work_state="TX"
        )
        db.add(employee)
        db.commit()
        employee_id = employee.id
        source = runs.create_pay_run(
            PayRunCreate(
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 14),
                pay_date=date(2026, 5, 15),
                stubs=[{"employee_id": employee_id, "hours": 80}],
            ),
            db,
        ).id
        runs.process_pay_run(source, db)
    start = Barrier(2)
    both_previewed = Barrier(2)
    compute = retro_pay.compute_retro_pay

    def overlap_after_preview(*args, **kwargs):
        preview = compute(*args, **kwargs)
        try:
            both_previewed.wait(timeout=1)
        except BrokenBarrierError:
            pass
        return preview

    monkeypatch.setattr(retro_pay, "compute_retro_pay", overlap_after_preview)

    def apply():
        with factory() as db:
            start.wait(timeout=10)
            try:
                result = retro_pay_apply(
                    RetroPayRequest(
                        employee_id=employee_id,
                        new_rate="25",
                        effective_date=date(2026, 5, 1),
                        pay_date=date(2026, 5, 29),
                    ),
                    db,
                )
                assert result["retro_pay"] == 400
                return 201
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply) for _ in range(2)]
        assert sorted(future.result(timeout=30) for future in futures) == [201, 409]
    with factory() as db:
        draft = db.query(PayRun).filter_by(status=PayRunStatus.DRAFT).one()
        assert draft.total_gross == Decimal("400")
        assert db.query(PayRun).count() == 2
