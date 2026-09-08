# ============================================================================
# Pay schedules — CRUD + upcoming-dates preview + employee attachment.
# ============================================================================

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.pay_schedules import PaySchedule, WeekendShift
from app.models.payroll import Employee, PayFrequency
from app.services.pay_schedule_service import upcoming_pay_dates
from app.schemas.common import StrictModel

router = APIRouter(prefix="/api/pay-schedules", tags=["pay-schedules"])


class PayScheduleCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    frequency: str
    anchor_pay_date: date
    submission_lead_days: int = Field(default=2, ge=0, le=365)
    weekend_shift: str = "previous_business_day"
    blackout_dates: list[date] = Field(default_factory=list, max_length=366)


class PayScheduleUpdate(StrictModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    frequency: Optional[str] = None
    anchor_pay_date: Optional[date] = None
    submission_lead_days: Optional[int] = Field(default=None, ge=0, le=365)
    weekend_shift: Optional[str] = None
    blackout_dates: Optional[list[date]] = Field(default=None, max_length=366)
    is_active: Optional[bool] = None


def _response(s: PaySchedule) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "frequency": s.frequency.value if s.frequency else None,
        "anchor_pay_date": s.anchor_pay_date.isoformat(),
        "submission_lead_days": s.submission_lead_days,
        "weekend_shift": s.weekend_shift.value if s.weekend_shift else None,
        "blackout_dates": sorted(
            value.isoformat() if isinstance(value, date) else value
            for value in (s.blackout_dates or [])
        ),
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


def _serialize_blackouts(values: list[date]) -> list[str]:
    return sorted({value.isoformat() for value in values})


def _clean_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Schedule name is required")
    return name


@router.get("")
def list_schedules(db: Session = Depends(get_db)):
    return [
        _response(s) for s in db.query(PaySchedule).order_by(PaySchedule.name).all()
    ]


@router.post("", status_code=201)
def create_schedule(data: PayScheduleCreate, db: Session = Depends(get_db)):
    freq, shift = _validate(data.frequency, data.weekend_shift)
    name = _clean_name(data.name)
    if db.query(PaySchedule).filter(PaySchedule.name == name).first():
        raise HTTPException(status_code=400, detail="Schedule name already exists")
    s = PaySchedule(
        name=name,
        frequency=freq,
        anchor_pay_date=data.anchor_pay_date,
        submission_lead_days=data.submission_lead_days,
        weekend_shift=shift,
        blackout_dates=_serialize_blackouts(data.blackout_dates),
    )
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Schedule name already exists")
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
        name = _clean_name(data.name)
        duplicate = (
            db.query(PaySchedule.id)
            .filter(PaySchedule.name == name, PaySchedule.id != schedule_id)
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="Schedule name already exists")
        s.name = name
    if freq is not None:
        s.frequency = freq
        db.query(Employee).filter(Employee.pay_schedule_id == schedule_id).update(
            {Employee.pay_frequency: freq}, synchronize_session=False
        )
    if data.anchor_pay_date is not None:
        s.anchor_pay_date = data.anchor_pay_date
    if data.submission_lead_days is not None:
        s.submission_lead_days = data.submission_lead_days
    if shift is not None:
        s.weekend_shift = shift
    if data.blackout_dates is not None:
        s.blackout_dates = _serialize_blackouts(data.blackout_dates)
    if data.is_active is not None:
        s.is_active = data.is_active
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Schedule name already exists")
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
    if not s.is_active:
        raise HTTPException(
            status_code=400, detail="Cannot assign an inactive schedule"
        )
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    emp.pay_schedule_id = s.id
    emp.pay_frequency = s.frequency
    db.commit()
    return {"employee_id": emp_id, "pay_schedule_id": s.id}
