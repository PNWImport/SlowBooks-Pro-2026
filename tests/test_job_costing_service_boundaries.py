"""Job cost validation, rounding conservation and period attribution."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.models.cost_codes import CostCode
from app.models.job_costing import JobCost, JobCostLine, JobBudget
from app.models.jobs import Job
from app.models.payroll import Employee, PayType, PayRun, PayStub
from app.models.benefits import PayStubBenefit
from app.models.time_entries import TimeEntry, TimeEntryStatus
from app.services import job_costing as service

DAY = date(2026, 7, 14)


def test_cost_code_import_validates_parents_and_updates_existing_names(db_session):
    result = service.import_cost_codes(
        db_session,
        [
            {"code": "", "name": "Missing code"},
            {"code": "A", "name": "Original"},
            {"code": "a", "name": "Updated", "parent_code": "missing"},
            {"code": "B", "name": "Self", "parent_code": "B"},
        ],
    )
    assert result["created"] == 2
    assert result["updated"] == 1
    assert len(result["errors"]) == 3
    assert db_session.query(CostCode).filter_by(code="A").one().name == "Updated"
    assert all(c.parent_id is None for c in db_session.query(CostCode))
    assert service.parse_cost_code_csv("\n , , \ncode,name\nC,Third\n") == [
        {"code": "C", "name": "Third", "cost_type": "other", "parent_code": ""}
    ]
    assert (
        service.code_depth(
            db_session, CostCode(code="ORPHAN", name="Orphan", parent_id=999999)
        )
        == 0
    )


def test_invalid_historical_number_falls_back_to_count(db_session):
    db_session.add(JobCost(number="JC-legacy", date=DAY))
    db_session.flush()
    assert service.next_job_cost_number(db_session) == "JC-000002"


def test_account_and_zero_amount_guards(db_session):
    with pytest.raises(ValueError, match="No offset account"):
        service.resolve_line_accounts(db_session, {}, None, "other", 1, None)
    jc = JobCost(number="JC-ZERO", date=DAY)
    jc.lines = [JobCostLine(amount=0, debit_account_id=1, credit_account_id=2)]
    with pytest.raises(ValueError, match="at least one line"):
        service.post_job_cost(db_session, jc)
    assert jc.transaction_id is None


def test_salary_cost_rate_and_invalid_time_entry_guards(db_session):
    emp = Employee(
        first_name="Salary", last_name="Test", pay_type=PayType.SALARY, pay_rate=52000
    )
    assert service.employee_cost_rate(emp) == D("25.0000")
    with pytest.raises(ValueError, match="no job"):
        service.post_time_entry_to_job(db_session, TimeEntry())
    with pytest.raises(ValueError, match="no hours"):
        service.post_time_entry_to_job(
            db_session,
            TimeEntry(
                job_id=1, employee=emp, status=TimeEntryStatus.APPROVED, hours_regular=0
            ),
        )


def test_spread_conserves_cents_and_handles_zero_weights():
    assert service._spread(D(1), {}) == {}
    assert service._spread(D(0), {1: D(1)}) == {}
    result = service._spread(D("0.01"), {1: D(1), 2: D(1), 3: D(1)})
    assert sum(result.values()) == D("0.01")
    assert result == {1: D("0.01"), 2: D("0.00"), 3: D("0.00")}


@pytest.mark.parametrize(
    "amount,method,expected",
    [(0, "equal", "positive"), (1, "hours", "Nothing to allocate")],
)
def test_allocation_requires_amount_and_weight(db_session, amount, method, expected):
    with pytest.raises(ValueError, match=expected):
        service.allocate_cost(
            db_session,
            txn_date=DAY,
            amount=D(amount),
            method=method,
            job_ids=[],
            cost_code_id=None,
            cost_type=None,
            debit_account_id=None,
            credit_account_id=None,
            memo=None,
            start_date=DAY,
            end_date=DAY,
        )


def test_allocation_hours_and_budget_changes_respect_job_and_period(
    db_session, seed_customer
):
    job = Job(name="Boundary job", customer_id=seed_customer.id)
    emp = Employee(first_name="Hours", last_name="Test")
    db_session.add_all([job, emp])
    db_session.flush()
    db_session.add_all(
        [
            TimeEntry(employee_id=emp.id, job_id=job.id, date=DAY, hours_regular=2),
            TimeEntry(
                employee_id=emp.id,
                job_id=job.id,
                date=date(2026, 7, 15),
                hours_regular=9,
            ),
            JobBudget(job_id=job.id, amount=125, source="change"),
        ]
    )
    db_session.commit()
    assert service.allocation_weights(db_session, "hours", [job.id], DAY, DAY) == {
        job.id: D(2)
    }
    assert service.allocation_weights(db_session, "equal", [job.id], None, None) == {
        job.id: D(1)
    }
    tree = service.job_cost_tree(db_session, job.id, DAY, DAY)
    assert tree["totals"]["changes"] == 125
    rows = service.budget_vs_actual_all_jobs(
        db_session, DAY, DAY, customer_id=seed_customer.id
    )
    assert len(rows) == 1
    assert rows[0]["changes"] == 125


@pytest.mark.parametrize("method", ["revenue", "costs"])
def test_allocation_profit_weights_exclude_nonpositive_values(
    db_session, monkeypatch, method
):
    def report(db, start, end, **kwargs):
        assert start == end == DAY
        assert kwargs == {"job_ids": [1, 2], "include_no_job": False}
        return [
            {"job_id": 1, "income": 10, "total_costs": 20},
            {"job_id": 2, "income": -5, "total_costs": 0},
        ]

    monkeypatch.setattr("app.services.jobs_service.job_profitability", report)
    assert service.allocation_weights(db_session, method, [1, 2], DAY, DAY) == {
        1: D(10 if method == "revenue" else 20)
    }


def test_payroll_burden_requires_expense_mapping(db_session):
    labor = service.cost_type_map(db_session)["labor"]
    labor.burden_method = "payroll"
    db_session.flush()
    run = PayRun(period_start=DAY, period_end=DAY, pay_date=DAY)
    with pytest.raises(ValueError, match="No payroll tax expense account"):
        service.distribute_payroll_burden(db_session, run)
    assert db_session.query(JobCost).count() == 0


@pytest.mark.parametrize("case", ["no_entries", "zero_hours", "zero_benefit"])
def test_payroll_burden_without_distributable_cost_creates_no_posting(
    db_session, seed_accounts, seed_customer, case
):
    labor = service.cost_type_map(db_session)["labor"]
    labor.burden_method = "payroll"
    emp = Employee(first_name="Burden", last_name="Test")
    job = Job(name="Burden job", customer_id=seed_customer.id)
    run = PayRun(period_start=DAY, period_end=DAY, pay_date=DAY)
    db_session.add_all([emp, job, run])
    db_session.flush()
    stub = PayStub(employee_id=emp.id, pay_run_id=run.id)
    db_session.add(stub)
    db_session.flush()
    if case != "no_entries":
        db_session.add(
            TimeEntry(
                employee_id=emp.id,
                job_id=job.id,
                pay_run_id=run.id,
                date=DAY,
                hours_regular=0 if case == "zero_hours" else 8,
            )
        )
    if case == "zero_benefit":
        db_session.add(
            PayStubBenefit(
                pay_stub_id=stub.id,
                code="ZERO",
                name="Zero",
                kind="benefit",
                category="pretax",
                calc_method="fixed_amount",
                burden_routing="job_burden",
                employer_amount=0,
            )
        )
    db_session.commit()
    assert service.distribute_payroll_burden(db_session, run) is None
    assert db_session.query(JobCost).count() == 0
