import json
from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import Field, model_validator

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.payroll._router import router
from app.routes.payroll.ytd import employee_ytd
from app.models.payroll import (
    PayRun,
    PayStub,
    PayRunStatus,
    PayRunType,
)
from app.services.payroll_service import calculate_withholdings
from app.services.state_tax.reciprocity import withholding_state
from app.services.payroll_drafts import (
    HISTORY_KEY,
    draft_history,
    lock_payroll_employees,
)
from app.schemas.common import Money, StrictModel
from app.services.retro_pay import RetroPayConflict


class RetroPayRequest(StrictModel):
    employee_id: int
    new_rate: Money = Field(gt=0, max_digits=15)
    effective_date: date
    pay_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_payment_date(self):
        if (self.pay_date or date.today()) < self.effective_date:
            raise ValueError("pay_date cannot be before effective_date")
        return self


@router.post("/retro-pay/preview")
def retro_pay_preview(data: RetroPayRequest, db: Session = Depends(get_db)):
    from app.services.retro_pay import compute_retro_pay

    try:
        return compute_retro_pay(
            db, data.employee_id, Decimal(str(data.new_rate)), data.effective_date
        )
    except RetroPayConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/retro-pay/apply", status_code=201)
def retro_pay_apply(data: RetroPayRequest, db: Session = Depends(get_db)):
    from app.services.retro_pay import compute_retro_pay

    emp = lock_payroll_employees(db, [data.employee_id]).get(data.employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if data.new_rate < (emp.pay_rate or 0):
        raise HTTPException(
            status_code=400,
            detail="Retro pay cannot lower the current pay rate. Reconcile rate decreases separately.",
        )
    try:
        preview = compute_retro_pay(
            db, data.employee_id, Decimal(str(data.new_rate)), data.effective_date
        )
    except RetroPayConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    amount = Decimal(str(preview["retro_pay_due"]))
    if any(period["difference"] < 0 for period in preview["periods"]):
        raise HTTPException(
            status_code=400,
            detail="Retro pay cannot subtract previously paid wages from another period's arrears. Reconcile the affected periods separately.",
        )
    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Retro amount is not positive — nothing to pay out",
        )

    # Remembered on the draft so cancelling it can undo the raise it staged.
    previous_rate = emp.pay_rate
    emp.pay_rate = Decimal(str(data.new_rate))

    pay_date = data.pay_date or date.today()
    run = PayRun(
        period_start=data.effective_date,
        period_end=pay_date,
        pay_date=pay_date,
        run_type=PayRunType.OFF_CYCLE,
        status=PayRunStatus.DRAFT,
    )
    db.add(run)
    db.flush()

    ytd = employee_ytd(db, emp.id, pay_date.year, before=pay_date)
    result = calculate_withholdings(
        amount,
        pay_frequency=emp.pay_frequency.value if emp.pay_frequency else "biweekly",
        filing_status=emp.filing_status.value if emp.filing_status else "single",
        ytd_gross=ytd["taxable_gross"],
        ytd_fica=ytd["fica_wages"],
        ytd_tips=ytd["tips"],
        work_state=(emp.work_state or "WA").upper(),
        withholding_state=withholding_state(
            (emp.work_state or "WA").upper(), emp.residence_state
        ),
        work_locality=emp.work_locality,
        residence_locality=emp.residence_locality,
        wc_class_code=emp.wc_class_code,
        supplemental=True,
    )
    stub = PayStub(
        pay_run_id=run.id,
        employee_id=emp.id,
        gross_pay=result["gross"],
        federal_tax=result["federal"],
        state_tax=result["state_income"],
        state_other_employee=result["state_other_employee"],
        local_tax=result["local_tax"],
        local_tax_employer=result["local_tax_employer"],
        ss_tax=result["ss"],
        medicare_tax=result["medicare"],
        work_state=(emp.work_state or "WA").upper(),
        work_locality=emp.work_locality,
        net_pay=result["net"],
        employer_ss_tax=result["employer_ss"],
        employer_medicare_tax=result["employer_medicare"],
        futa_tax=result["futa"],
        suta_tax=result["suta"],
        state_other_employer=result["state_other_employer"],
        detail_json=json.dumps(
            {k: str(v) for k, v in result["detail"].items()}
            | {
                "retro_pay": str(amount),
                "retro_previous_pay_rate": str(previous_rate),
                "retro_new_pay_rate": str(Decimal(str(data.new_rate))),
                "effective_date": str(data.effective_date),
                "retro_source_run_ids": [
                    period["pay_run_id"]
                    for period in preview["periods"]
                    if period["difference"] > 0
                ],
                HISTORY_KEY: draft_history(db, emp.id, pay_date),
            }
        ),
    )
    db.add(stub)
    run.total_gross = result["gross"]
    run.total_taxes = result["total_employee_tax"]
    run.total_employer_taxes = result["total_employer_tax"]
    run.total_net = result["net"]
    db.commit()
    return {
        "pay_run_id": run.id,
        "retro_pay": float(amount),
        "new_rate": data.new_rate,
        "status": "draft",
        "periods": preview["periods"],
    }
