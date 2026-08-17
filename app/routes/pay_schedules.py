# ============================================================================
# Pay schedules — CRUD + upcoming-dates preview + employee attachment.
# ============================================================================

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.pay_schedules import PaySchedule, WeekendShift
from app.models.payroll import Employee, PayFrequency
from app.services.pay_schedule_service import upcoming_pay_dates

router = APIRouter(prefix="/api/pay-schedules", tags=["pay-schedules"])


class PayScheduleCreate(BaseModel):
    name: str
    frequency: str
    anchor_pay_date: date
    submission_lead_days: int = 2
    weekend_shift: str = "previous_business_day"


class PayScheduleUpdate(BaseModel):
    name: Optional[str] = None
    frequency: Optional[str] = None
    anchor_pay_date: Optional[date] = None
    submission_lead_days: Optional[int] = None
    weekend_shift: Optional[str] = None
    is_active: Optional[bool] = None


def _response(s: PaySchedule) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "frequency": s.frequency.value if s.frequency else None,
        "anchor_pay_date": s.anchor_pay_date.isoformat(),
        "submission_lead_days": s.submission_lead_days,
        "weekend_shift": s.weekend_shift.value if s.weekend_shift else None,
        "is_active": bool(s.is_active),
    }


def _validate(frequency: str | None, weekend_shift: str | None):
    freq = shift = None
    if frequency is not None:
        try:
            freq = PayFrequency(frequency)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid frequency {frequency!r}"
            )
    if weekend_shift is not None:
        try:
            shift = WeekendShift(weekend_shift)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid weekend_shift {weekend_shift!r}"
            )
    return freq, shift


@router.get("")
def list_schedules(db: Session = Depends(get_db)):
    return [
        _response(s) for s in db.query(PaySchedule).order_by(PaySchedule.name).all()
    ]


@router.post("", status_code=201)
def create_schedule(data: PayScheduleCreate, db: Session = Depends(get_db)):
    freq, shift = _validate(data.frequency, data.weekend_shift)
    if db.query(PaySchedule).filter(PaySchedule.name == data.name).first():
        raise HTTPException(status_code=400, detail="Schedule name already exists")
    if data.submission_lead_days < 0:
        raise HTTPException(status_code=400, detail="lead days must be >= 0")
    s = PaySchedule(
        name=data.name,
        frequency=freq,
        anchor_pay_date=data.anchor_pay_date,
        submission_lead_days=data.submission_lead_days,
        weekend_shift=shift,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _response(s)


@router.put("/{schedule_id}")
def update_schedule(
    schedule_id: int, data: PayScheduleUpdate, db: Session = Depends(get_db)
):
    s = db.query(PaySchedule).filter(PaySchedule.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    freq, shift = _validate(data.frequency, data.weekend_shift)
    if data.name is not None:
        s.name = data.name
    if freq is not None:
        s.frequency = freq
    if data.anchor_pay_date is not None:
        s.anchor_pay_date = data.anchor_pay_date
    if data.submission_lead_days is not None:
        if data.submission_lead_days < 0:
            raise HTTPException(status_code=400, detail="lead days must be >= 0")
        s.submission_lead_days = data.submission_lead_days
    if shift is not None:
        s.weekend_shift = shift
    if data.is_active is not None:
        s.is_active = data.is_active
    db.commit()
    return _response(s)


@router.get("/{schedule_id}/upcoming")
def upcoming(
    schedule_id: int,
    count: int = Query(default=12, ge=1, le=60),
    start: date = Query(default=None),
    db: Session = Depends(get_db),
):
    """Preview the next pay dates + submission cutoffs for a schedule."""
    s = db.query(PaySchedule).filter(PaySchedule.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {
        "schedule": _response(s),
        "dates": upcoming_pay_dates(s, start or date.today(), count),
    }


@router.post("/{schedule_id}/assign/{emp_id}")
def assign_employee(schedule_id: int, emp_id: int, db: Session = Depends(get_db)):
    """Attach an employee; their pay_frequency follows the schedule's."""
    s = db.query(PaySchedule).filter(PaySchedule.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    emp.pay_schedule_id = s.id
    emp.pay_frequency = s.frequency
    db.commit()
    return {"employee_id": emp_id, "pay_schedule_id": s.id}
