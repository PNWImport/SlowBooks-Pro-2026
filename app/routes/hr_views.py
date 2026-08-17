# ============================================================================
# HR views — org chart, team PTO calendar, performance reviews.
# ============================================================================

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.payroll import Employee
from app.models.pto import PTORequest, PTORequestStatus
from app.models.reviews import PerformanceReview, ReviewStatus

router = APIRouter(prefix="/api/hr", tags=["hr-views"])


# --- Org chart ---------------------------------------------------------------


@router.get("/org-chart")
def org_chart(include_inactive: bool = False, db: Session = Depends(get_db)):
    """The manager tree from Employee.manager_id.

    Cycles (A manages B manages A — possible because manager_id is
    unconstrained) are broken at the second visit and reported, not
    500'd. Employees whose manager is missing/inactive surface as roots.
    """
    q = db.query(Employee)
    if not include_inactive:
        q = q.filter(Employee.is_active.is_(True))
    employees = q.all()
    by_id = {e.id: e for e in employees}

    children: dict[int, list] = {}
    roots: list[Employee] = []
    for e in employees:
        if e.manager_id and e.manager_id in by_id and e.manager_id != e.id:
            children.setdefault(e.manager_id, []).append(e)
        else:
            roots.append(e)

    cycles: list[int] = []
    visited: set[int] = set()

    def _node(e: Employee) -> dict:
        if e.id in visited:
            cycles.append(e.id)
            return {"id": e.id, "name": e.full_name, "cycle": True, "reports": []}
        visited.add(e.id)
        return {
            "id": e.id,
            "name": e.full_name,
            "role": e.role.value if e.role else None,
            "is_active": bool(e.is_active),
            "reports": [
                _node(c)
                for c in sorted(children.get(e.id, []), key=lambda x: x.full_name)
            ],
        }

    tree = [_node(r) for r in sorted(roots, key=lambda x: x.full_name)]
    # Anyone unreached (a pure cycle disconnected from any root) still shows.
    orphans = [_node(e) for e in employees if e.id not in visited]
    return {"tree": tree + orphans, "cycle_employee_ids": sorted(set(cycles))}


# --- Team PTO calendar -------------------------------------------------------


@router.get("/pto-calendar")
def pto_calendar(
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
):
    """Approved (and pending, flagged) PTO overlapping the window."""
    if end < start:
        raise HTTPException(status_code=400, detail="end before start")
    rows = (
        db.query(PTORequest)
        .options(joinedload(PTORequest.employee))
        .filter(
            PTORequest.status.in_(
                [PTORequestStatus.APPROVED, PTORequestStatus.PENDING]
            ),
            PTORequest.start_date <= end,
            PTORequest.end_date >= start,
        )
        .order_by(PTORequest.start_date)
        .all()
    )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "entries": [
            {
                "employee_id": r.employee_id,
                "employee_name": r.employee.full_name if r.employee else None,
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat(),
                "pto_type": r.pto_type.value if r.pto_type else None,
                "hours": float(r.hours or 0),
                "status": r.status.value,
            }
            for r in rows
        ],
    }


# --- Performance reviews -----------------------------------------------------


class ReviewCreate(BaseModel):
    employee_id: int
    reviewer_id: Optional[int] = None
    period_start: date
    period_end: date
    rating: Optional[int] = None
    goals: Optional[str] = None
    feedback: Optional[str] = None


class ReviewUpdate(BaseModel):
    rating: Optional[int] = None
    goals: Optional[str] = None
    feedback: Optional[str] = None


class AcknowledgeRequest(BaseModel):
    employee_comment: Optional[str] = None


def _review_response(r: PerformanceReview) -> dict:
    return {
        "id": r.id,
        "employee_id": r.employee_id,
        "employee_name": r.employee.full_name if r.employee else None,
        "reviewer_id": r.reviewer_id,
        "reviewer_name": r.reviewer.full_name if r.reviewer else None,
        "period_start": r.period_start.isoformat(),
        "period_end": r.period_end.isoformat(),
        "status": r.status.value if r.status else None,
        "rating": r.rating,
        "goals": r.goals,
        "feedback": r.feedback,
        "employee_comment": r.employee_comment,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        "acknowledged_at": (
            r.acknowledged_at.isoformat() if r.acknowledged_at else None
        ),
    }


def _check_rating(rating):
    if rating is not None and not (1 <= rating <= 5):
        raise HTTPException(status_code=400, detail="rating must be 1-5")


@router.get("/reviews")
def list_reviews(employee_id: int = Query(default=None), db: Session = Depends(get_db)):
    q = db.query(PerformanceReview).options(
        joinedload(PerformanceReview.employee),
        joinedload(PerformanceReview.reviewer),
    )
    if employee_id is not None:
        q = q.filter(PerformanceReview.employee_id == employee_id)
    return [
        _review_response(r)
        for r in q.order_by(PerformanceReview.period_end.desc()).all()
    ]


@router.post("/reviews", status_code=201)
def create_review(data: ReviewCreate, db: Session = Depends(get_db)):
    if not db.query(Employee).filter(Employee.id == data.employee_id).first():
        raise HTTPException(status_code=404, detail="Employee not found")
    if data.period_end < data.period_start:
        raise HTTPException(status_code=400, detail="period end before start")
    _check_rating(data.rating)
    r = PerformanceReview(
        employee_id=data.employee_id,
        reviewer_id=data.reviewer_id,
        period_start=data.period_start,
        period_end=data.period_end,
        rating=data.rating,
        goals=data.goals,
        feedback=data.feedback,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return _review_response(r)


@router.put("/reviews/{review_id}")
def update_review(review_id: int, data: ReviewUpdate, db: Session = Depends(get_db)):
    r = db.query(PerformanceReview).filter(PerformanceReview.id == review_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Review not found")
    if r.status != ReviewStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only drafts are editable")
    _check_rating(data.rating)
    for field in ("rating", "goals", "feedback"):
        value = getattr(data, field)
        if value is not None:
            setattr(r, field, value)
    db.commit()
    return _review_response(r)


@router.post("/reviews/{review_id}/submit")
def submit_review(review_id: int, db: Session = Depends(get_db)):
    r = db.query(PerformanceReview).filter(PerformanceReview.id == review_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Review not found")
    if r.status != ReviewStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Already submitted")
    r.status = ReviewStatus.SUBMITTED
    r.submitted_at = datetime.now(timezone.utc)
    db.commit()
    return _review_response(r)


@router.post("/reviews/{review_id}/acknowledge")
def acknowledge_review(
    review_id: int, data: AcknowledgeRequest, db: Session = Depends(get_db)
):
    r = db.query(PerformanceReview).filter(PerformanceReview.id == review_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Review not found")
    if r.status != ReviewStatus.SUBMITTED:
        raise HTTPException(
            status_code=400, detail="Only submitted reviews can be acknowledged"
        )
    r.status = ReviewStatus.ACKNOWLEDGED
    r.acknowledged_at = datetime.now(timezone.utc)
    r.employee_comment = data.employee_comment
    db.commit()
    return _review_response(r)
