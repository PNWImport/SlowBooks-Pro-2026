# ============================================================================
# Workers' comp — carrier class rates + the annual premium report.
# ============================================================================

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.payroll import PayRun, PayRunStatus, PayStub
from app.models.workers_comp import WCClassRate
from app.schemas.common import StrictModel

router = APIRouter(prefix="/api/workers-comp", tags=["workers-comp"])

CENT = Decimal("0.01")


class RateCreate(StrictModel):
    class_code: str
    state: str
    rate_per_100: float
    description: Optional[str] = None


def _rate_response(r: WCClassRate) -> dict:
    return {
        "id": r.id,
        "class_code": r.class_code,
        "state": r.state,
        "description": r.description,
        "rate_per_100": float(r.rate_per_100 or 0),
        "is_active": bool(r.is_active),
    }


@router.get("/rates")
def list_rates(db: Session = Depends(get_db)):
    rows = (
        db.query(WCClassRate).order_by(WCClassRate.state, WCClassRate.class_code).all()
    )
    return [_rate_response(r) for r in rows]


@router.post("/rates", status_code=201)
def create_rate(data: RateCreate, db: Session = Depends(get_db)):
    if data.rate_per_100 < 0:
        raise HTTPException(status_code=400, detail="rate must be >= 0")
    state = data.state.strip().upper()
    if len(state) != 2:
        raise HTTPException(status_code=400, detail="state must be 2 letters")
    existing = (
        db.query(WCClassRate)
        .filter(
            WCClassRate.class_code == data.class_code,
            WCClassRate.state == state,
            WCClassRate.is_active.is_(True),
        )
        .first()
    )
    # New rate supersedes the old one for the same (state, class).
    if existing:
        existing.is_active = False
    row = WCClassRate(
        class_code=data.class_code,
        state=state,
        description=data.description,
        rate_per_100=Decimal(str(data.rate_per_100)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _rate_response(row)


@router.get("/premium-report")
def premium_report(year: int = Query(...), db: Session = Depends(get_db)):
    """The carrier premium-audit view: wages and premium by (state, class).

    Groups the year's processed stubs by work state and the employee's WC
    class code; premium = wages / 100 x the active carrier rate. Stubs
    whose class has no rate on file are reported with premium None so
    missing rates are visible instead of silently pricing at zero.
    """
    stubs = (
        db.query(PayStub)
        .join(PayRun, PayStub.pay_run_id == PayRun.id)
        .options(joinedload(PayStub.employee))
        .filter(
            PayRun.status == PayRunStatus.PROCESSED,
            PayRun.pay_date >= date(year, 1, 1),
            PayRun.pay_date <= date(year, 12, 31),
        )
        .all()
    )

    rates = {
        (r.state, r.class_code): Decimal(str(r.rate_per_100))
        for r in db.query(WCClassRate).filter(WCClassRate.is_active.is_(True)).all()
    }

    groups: dict[tuple, dict] = {}
    for s in stubs:
        emp = s.employee
        class_code = (emp.wc_class_code if emp else None) or "UNCLASSIFIED"
        state = (s.work_state or (emp.work_state if emp else None) or "??").upper()
        key = (state, class_code)
        group = groups.setdefault(
            key,
            {
                "state": state,
                "class_code": class_code,
                "wages": Decimal("0"),
                "hours": Decimal("0"),
                "employee_ids": set(),
            },
        )
        group["wages"] += Decimal(str(s.gross_pay or 0))
        group["hours"] += Decimal(str(s.hours or 0))
        group["employee_ids"].add(s.employee_id)

    rows = []
    total_premium = Decimal("0")
    missing = []
    for key in sorted(groups):
        group = groups[key]
        rate = rates.get(key)
        premium = None
        if rate is not None:
            premium = (group["wages"] / 100 * rate).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
            total_premium += premium
        else:
            missing.append(f"{key[0]}:{key[1]}")
        rows.append(
            {
                "state": group["state"],
                "class_code": group["class_code"],
                "employees": len(group["employee_ids"]),
                "wages": float(group["wages"].quantize(CENT)),
                "hours": float(group["hours"]),
                "rate_per_100": float(rate) if rate is not None else None,
                "premium": float(premium) if premium is not None else None,
            }
        )

    return {
        "year": year,
        "rows": rows,
        "total_premium": float(total_premium),
        "classes_missing_rates": missing,
    }
