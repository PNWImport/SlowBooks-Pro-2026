"""Serialize payroll decisions and preserve a draft's reviewed wage history.

Draft benefits reserve deductions immediately, but unpaid drafts never consume
tax wage bases. Processing must therefore verify the history the operator
reviewed, rather than silently change taxes or reuse an annual allowance.
"""

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

from app.models.payroll import Employee, PayRun, PayRunStatus, PayRunType, PayStub
from app.models.benefits import BenefitCode, BenefitYTD, EmployeeBenefit
from app.services.payroll_wages import federal_wages

HISTORY_KEY = "_payroll_history"


def begin_payroll_write(db: Session) -> None:
    """Take SQLite's writer reservation before reading payroll decisions."""
    conn = db.connection()
    if conn.dialect.name == "sqlite" and not getattr(
        conn.connection.driver_connection, "in_transaction", False
    ):
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def lock_payroll_employees(db: Session, employee_ids) -> dict[int, Employee]:
    """All staging, processing and cancellation share this ordered lock."""
    begin_payroll_write(db)
    db.flush()
    return {
        employee.id: employee
        for employee in (
            db.query(Employee)
            .filter(Employee.id.in_(set(employee_ids)))
            .order_by(Employee.id)
            .with_for_update()
            .populate_existing()
            .all()
        )
    }


def draft_history(
    db: Session, employee_id: int, pay_date: date, *, aggregate: bool = False
) -> dict:
    """Fingerprint only immutable paid snapshots, never current plan settings."""
    stubs = (
        db.query(PayStub)
        .join(PayRun, PayStub.pay_run_id == PayRun.id)
        .options(selectinload(PayStub.benefits))
        .filter(
            PayStub.employee_id == employee_id,
            PayRun.status == PayRunStatus.PROCESSED,
            PayRun.pay_date >= date(pay_date.year, 1, 1),
            PayRun.pay_date <= pay_date,
        )
        .order_by(PayRun.pay_date, PayStub.id)
        .populate_existing()
        .all()
    )
    history = [
        {
            "id": stub.id,
            "run_id": stub.pay_run_id,
            "pay_date": str(stub.pay_run.pay_date),
            "run_type": stub.pay_run.run_type.value,
            "gross": str(stub.gross_pay or 0),
            "pretax": str(stub.pretax_deductions or 0),
            "reported_tips": str(stub.reported_tips or 0),
            "paycheck_tips": str(stub.paycheck_tips or 0),
            "earnings": _earnings_snapshot(stub),
            "benefits": [
                {
                    "id": benefit.id,
                    "category": benefit.category,
                    "employee": str(benefit.employee_amount or 0),
                    "employer": str(benefit.employer_amount or 0),
                    "federal": benefit.reduces_federal,
                    "state": benefit.reduces_state,
                    "fica": benefit.reduces_fica,
                    "rule": benefit.rule_json,
                }
                for benefit in sorted(stub.benefits, key=lambda row: row.id)
            ],
        }
        for stub in stubs
    ]
    digest = hashlib.sha256(
        json.dumps(history, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    # An aggregate supplemental payment may refer to the last paid regular
    # check in the previous calendar year. Preserve that separate dependency
    # as well as this year's cap history.
    regular = (
        (
            db.query(PayStub)
            .join(PayRun, PayStub.pay_run_id == PayRun.id)
            .options(selectinload(PayStub.benefits))
            .filter(
                PayStub.employee_id == employee_id,
                PayRun.status == PayRunStatus.PROCESSED,
                PayRun.run_type == PayRunType.REGULAR,
                PayRun.pay_date <= pay_date,
            )
            .order_by(PayRun.pay_date.desc(), PayStub.id.desc())
            .populate_existing()
            .first()
        )
        if aggregate
        else None
    )
    return {
        "version": 1,
        "employee_id": employee_id,
        "pay_date": str(pay_date),
        "sha256": digest,
        "aggregate": aggregate,
        "regular_reference": (
            {"id": regular.id, "federal_wages": str(federal_wages(regular))}
            if regular
            else None
        ),
    }


def _earnings_snapshot(stub):
    try:
        detail = json.loads(stub.detail_json or "null")
    except (TypeError, ValueError):
        return None
    return detail.get("_payroll_earnings") if isinstance(detail, dict) else None


def validate_draft_history(db: Session, run: PayRun) -> None:
    """Hold stale/unverifiable drafts without altering reviewed amounts."""
    employee_ids = [stub.employee_id for stub in run.stubs]
    if len(employee_ids) != len(set(employee_ids)):
        raise HTTPException(
            status_code=409,
            detail="Payroll must have one stub per employee. Cancel and review this draft.",
        )
    for stub in run.stubs:
        for benefit in stub.benefits:
            if not benefit.employer_amount:
                continue
            try:
                rule = json.loads(benefit.rule_json or "null")
                if isinstance(rule, dict) and rule.get("employer_taxable"):
                    amount = Decimal(str(rule.get("taxable_employer_amount")))
                    if not amount.is_finite() or amount != benefit.employer_amount:
                        rule = None
            except (TypeError, ValueError, InvalidOperation):
                rule = None
            if not isinstance(rule, dict) or (
                rule.get("employer_taxable")
                and (rule.get("employer_tax_treatment") != "fully_taxable")
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Employee {stub.employee_id}'s draft employer benefit tax "
                        "treatment is unverified. Cancel and recreate it for review."
                    ),
                )
        later = (
            db.query(PayRun.id)
            .join(PayStub, PayStub.pay_run_id == PayRun.id)
            .filter(
                PayStub.employee_id == stub.employee_id,
                PayRun.status == PayRunStatus.PROCESSED,
                PayRun.pay_date > run.pay_date,
                PayRun.pay_date <= date(run.pay_date.year, 12, 31),
            )
            .first()
        )
        if later:
            hint = (
                ' For a PTO payout: cancel this draft, then use "PTO payout" on '
                "the Employees page to stage it again on a date it can be paid."
                if '"pto_payout"' in (stub.detail_json or "")
                else ""
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    "A check with a later pay date has already been processed for "
                    f"employee {stub.employee_id}. This draft cannot change paid "
                    "tax history. Cancel it and review the payment date." + hint
                ),
            )
        try:
            detail = json.loads(stub.detail_json or "null")
            baseline = detail.get(HISTORY_KEY) if isinstance(detail, dict) else None
        except (TypeError, ValueError):
            baseline = None
        if not isinstance(baseline, dict) or baseline.get("version") != 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Employee {stub.employee_id}'s draft has no verified payroll "
                    "history. Cancel and recreate it for review; legacy benefit "
                    "reservations may require administrator reconciliation."
                ),
            )
        if "retro_pay" in detail:
            source_ids = detail.get("retro_source_run_ids")
            if (
                not isinstance(source_ids, list)
                or not source_ids
                or any(
                    not isinstance(source_id, int)
                    or isinstance(source_id, bool)
                    or source_id <= 0
                    for source_id in source_ids
                )
                or len(source_ids) != len(set(source_ids))
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Retro source claims are unverified; review this draft.",
                )
            paid_ids = {
                source_id
                for (source_id,) in db.query(PayRun.id)
                .join(PayStub, PayStub.pay_run_id == PayRun.id)
                .filter(
                    PayRun.id.in_(source_ids),
                    PayRun.status == PayRunStatus.PROCESSED,
                    PayRun.run_type == PayRunType.REGULAR,
                    PayStub.employee_id == stub.employee_id,
                )
                .all()
            }
            if paid_ids != set(source_ids):
                raise HTTPException(
                    status_code=409,
                    detail="Retro source claims no longer match paid employee earnings; review this draft.",
                )
            from app.services.retro_pay import (
                RetroPayConflict,
                _refuse_overlapping_retro,
            )

            try:
                _refuse_overlapping_retro(
                    db, stub.employee_id, paid_ids, exclude_run_id=run.id
                )
            except RetroPayConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not isinstance(baseline.get("aggregate"), bool) or baseline != draft_history(
            db, stub.employee_id, run.pay_date, aggregate=baseline["aggregate"]
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Employee {stub.employee_id}'s paid payroll history has changed "
                    "since this draft was calculated. Cancel and recreate the draft "
                    "to review updated taxes and net pay. Saved amounts were preserved."
                ),
            )


def release_draft_reservations(
    db: Session, run: PayRun, acknowledge_unverified_loans: bool = False
) -> list[dict]:
    """Refund a draft's reservations; never infer a legacy loan owner.

    Validate every reservation before mutating any row. Employee locks are
    held by the caller, matching staging's lock order and preventing refund
    races with another draft's cap/loan calculation.

    A draft staged before reservations were recorded has no marker on its
    benefit lines. What staging did to the year-to-date totals is exactly
    knowable (it always added the line's amounts), so that is refunded. What
    it did to a loan balance is not: only a code that tracks a balance moved
    one, and which assignment and by how much was never written down. Those
    lines are returned for review instead; cancelling needs the person to
    say they will check those balances by hand
    (`acknowledge_unverified_loans`), and nothing is changed without that.
    A marker that is present but wrong is still a refusal: that is damage,
    not age.
    """
    ytd_refunds = {}
    loan_refunds = {}
    loan_review = []
    tracked_codes = {
        code_id
        for (code_id,) in db.query(BenefitCode.id).filter(
            BenefitCode.tracks_balance.is_(True)
        )
    }

    def refuse():
        raise HTTPException(
            status_code=409,
            detail=(
                "This draft's benefit reservations cannot be verified. "
                "An administrator must reconcile them before cancellation. "
                "No reservations or stored payroll amounts were changed."
            ),
        )

    for stub in run.stubs:
        for benefit in stub.benefits:
            employee_amount = Decimal(str(benefit.employee_amount or 0))
            employer_amount = Decimal(str(benefit.employer_amount or 0))
            if (
                not employee_amount.is_finite()
                or not employer_amount.is_finite()
                or employee_amount < 0
                or employer_amount < 0
            ):
                refuse()
            if employee_amount == 0 and employer_amount == 0:
                continue
            try:
                rule = json.loads(benefit.rule_json or "null")
                if benefit.benefit_code_id is None or not isinstance(rule, dict):
                    refuse()
                legacy = "draft_reservation" not in rule
                marker = None if legacy else rule["draft_reservation"]
                if legacy:
                    reserved = Decimal("0")
                    if benefit.benefit_code_id in tracked_codes and employee_amount:
                        loan_review.append(
                            {
                                "employee_id": stub.employee_id,
                                "code": benefit.code,
                                "name": benefit.name,
                                "amount": str(employee_amount),
                            }
                        )
                else:
                    if (
                        not isinstance(marker, dict)
                        or marker.get("version") != 1
                        or marker.get("year") != run.pay_date.year
                    ):
                        refuse()
                    reserved = Decimal(str(marker.get("balance_reserved")))
                    if (
                        not reserved.is_finite()
                        or reserved < 0
                        or reserved > employee_amount
                        or reserved != reserved.quantize(Decimal("0.01"))
                    ):
                        refuse()
            except (TypeError, ValueError, InvalidOperation):
                refuse()
            key = (stub.employee_id, benefit.benefit_code_id, run.pay_date.year)
            prior = ytd_refunds.get(key, (Decimal("0"), Decimal("0")))
            ytd_refunds[key] = (prior[0] + employee_amount, prior[1] + employer_amount)
            if reserved:
                assignment_id = marker.get("assignment_id")
                if not isinstance(assignment_id, int) or isinstance(
                    assignment_id, bool
                ):
                    refuse()
                key = (assignment_id, stub.employee_id, benefit.benefit_code_id)
                loan_refunds[key] = loan_refunds.get(key, Decimal("0")) + reserved

    if loan_review and not acknowledge_unverified_loans:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "legacy_loan_review",
                "message": (
                    "This draft was staged before loan reservations were "
                    "recorded, so SlowBooks cannot tell which loan balance it "
                    "reduced or by how much. Cancelling releases its year-to-date "
                    "totals, but the loan balances below must be checked by hand."
                ),
                "loans": loan_review,
            },
        )

    ytd_changes = []
    for (employee_id, code_id, year), (employee_amount, employer_amount) in sorted(
        ytd_refunds.items()
    ):
        row = (
            db.query(BenefitYTD)
            .filter_by(employee_id=employee_id, benefit_code_id=code_id, year=year)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if (
            row is None
            or row.employee_amount < employee_amount
            or row.employer_amount < employer_amount
        ):
            refuse()
        ytd_changes.append((row, employee_amount, employer_amount))

    loan_changes = []
    for (assignment_id, employee_id, code_id), amount in sorted(loan_refunds.items()):
        row = (
            db.query(EmployeeBenefit)
            .filter_by(
                id=assignment_id, employee_id=employee_id, benefit_code_id=code_id
            )
            .with_for_update()
            .populate_existing()
            .first()
        )
        if row is None or row.balance_remaining is None:
            refuse()
        loan_changes.append((row, amount))

    for row, employee_amount, employer_amount in ytd_changes:
        row.employee_amount -= employee_amount
        row.employer_amount -= employer_amount
    for row, amount in loan_changes:
        row.balance_remaining += amount
    return loan_review
