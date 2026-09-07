# ============================================================================
# Benefits — plan CRUD, enrollment, dependents, COBRA election notices.
# ============================================================================

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.benefit_coverage import (
    BenefitDependent,
    BenefitEnrollment,
    BenefitKind,
    BenefitPlan,
    EnrollmentStatus,
)
from app.models.payroll import Employee
from app.schemas.common import StrictModel

router = APIRouter(prefix="/api/benefit-coverage", tags=["benefit-coverage"])


class PlanCreate(StrictModel):
    name: str
    kind: str = "medical"
    carrier_name: Optional[str] = None
    self_insured: bool = False
    provides_mec: bool = True
    monthly_premium_employee: float = 0
    monthly_premium_employer: float = 0


class EnrollRequest(StrictModel):
    employee_id: int
    plan_id: int
    coverage_start: date


class EndEnrollmentRequest(StrictModel):
    coverage_end: date


class DependentCreate(StrictModel):
    name: str
    relationship_kind: Optional[str] = None
    ssn_last_four: Optional[str] = None
    dob: Optional[date] = None


def _plan_response(p: BenefitPlan) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "kind": p.kind.value if p.kind else None,
        "carrier_name": p.carrier_name,
        "self_insured": bool(p.self_insured),
        "provides_mec": bool(p.provides_mec),
        "monthly_premium_employee": float(p.monthly_premium_employee or 0),
        "monthly_premium_employer": float(p.monthly_premium_employer or 0),
        "is_active": bool(p.is_active),
    }


def _enrollment_response(e: BenefitEnrollment) -> dict:
    return {
        "id": e.id,
        "employee_id": e.employee_id,
        "employee_name": e.employee.full_name if e.employee else None,
        "plan_id": e.plan_id,
        "plan_name": e.plan.name if e.plan else None,
        # The UI needs the kind to know whether COBRA applies to this
        # enrollment. Joining plans client-side to find that out would be a
        # client re-implementing a server rule; `kind` is decrypted here
        # anyway (see app/models/benefits.py on why it is encrypted).
        "plan_kind": (e.plan.kind.value if e.plan and e.plan.kind else None),
        "coverage_start": e.coverage_start.isoformat(),
        "coverage_end": e.coverage_end.isoformat() if e.coverage_end else None,
        "status": e.status.value if e.status else None,
        "dependents": [
            {
                "id": d.id,
                "name": d.name,
                "relationship_kind": d.relationship_kind,
            }
            for d in e.dependents
        ],
    }


# --- plans -------------------------------------------------------------------


@router.get("/plans")
def list_plans(db: Session = Depends(get_db)):
    return [
        _plan_response(p)
        for p in db.query(BenefitPlan).order_by(BenefitPlan.name).all()
    ]


@router.post("/plans", status_code=201)
def create_plan(data: PlanCreate, db: Session = Depends(get_db)):
    try:
        kind = BenefitKind(data.kind)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid kind {data.kind!r}")
    if db.query(BenefitPlan).filter(BenefitPlan.name == data.name).first():
        raise HTTPException(status_code=400, detail="Plan name already exists")
    plan = BenefitPlan(
        name=data.name,
        kind=kind,
        carrier_name=data.carrier_name,
        self_insured=data.self_insured,
        provides_mec=data.provides_mec,
        monthly_premium_employee=data.monthly_premium_employee,
        monthly_premium_employer=data.monthly_premium_employer,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _plan_response(plan)


# --- enrollment --------------------------------------------------------------


@router.get("/enrollments")
def list_enrollments(
    employee_id: int = Query(default=None), db: Session = Depends(get_db)
):
    q = db.query(BenefitEnrollment).options(
        joinedload(BenefitEnrollment.plan),
        joinedload(BenefitEnrollment.employee),
        joinedload(BenefitEnrollment.dependents),
    )
    if employee_id is not None:
        q = q.filter(BenefitEnrollment.employee_id == employee_id)
    return [_enrollment_response(e) for e in q.all()]


@router.post("/enrollments", status_code=201)
def enroll(data: EnrollRequest, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == data.employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    plan = db.query(BenefitPlan).filter(BenefitPlan.id == data.plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    duplicate = (
        db.query(BenefitEnrollment)
        .filter(
            BenefitEnrollment.employee_id == data.employee_id,
            BenefitEnrollment.plan_id == data.plan_id,
            BenefitEnrollment.coverage_end.is_(None),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=400, detail="Employee already has an open enrollment"
        )
    enrollment = BenefitEnrollment(
        employee_id=data.employee_id,
        plan_id=data.plan_id,
        coverage_start=data.coverage_start,
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return _enrollment_response(enrollment)


@router.post("/enrollments/{enrollment_id}/end")
def end_enrollment(
    enrollment_id: int, data: EndEnrollmentRequest, db: Session = Depends(get_db)
):
    e = (
        db.query(BenefitEnrollment)
        .filter(BenefitEnrollment.id == enrollment_id)
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    if e.coverage_end is not None:
        raise HTTPException(status_code=400, detail="Enrollment already ended")
    if data.coverage_end < e.coverage_start:
        raise HTTPException(status_code=400, detail="end before start")
    e.coverage_end = data.coverage_end
    e.status = EnrollmentStatus.TERMINATED
    db.commit()
    return _enrollment_response(e)


@router.post("/enrollments/{enrollment_id}/dependents", status_code=201)
def add_dependent(
    enrollment_id: int, data: DependentCreate, db: Session = Depends(get_db)
):
    e = (
        db.query(BenefitEnrollment)
        .filter(BenefitEnrollment.id == enrollment_id)
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    dep = BenefitDependent(
        enrollment_id=enrollment_id,
        name=data.name,
        relationship_kind=data.relationship_kind,
        ssn_last_four=data.ssn_last_four,
        dob=data.dob,
    )
    db.add(dep)
    db.commit()
    return {"id": dep.id, "name": dep.name}


# --- COBRA -------------------------------------------------------------------


@router.post("/enrollments/{enrollment_id}/cobra-notice")
def cobra_notice(enrollment_id: int, db: Session = Depends(get_db)):
    """Render a COBRA election notice PDF for an ENDED medical enrollment.

    General-notice content: qualifying event date (coverage end), the plan,
    the 60-day election window, and the premium at 102% (the statutory
    admin-fee cap). Audit-hashed like the tax forms. A generic template —
    review against DOL model notices before sending.
    """
    from app.routes.payroll.tax_forms import _company_for_pdf, _hash_and_audit, _pdf_response
    from app.services.pdf_service import _jinja_env, _safe_url_fetcher
    from weasyprint import HTML

    e = (
        db.query(BenefitEnrollment)
        .options(
            joinedload(BenefitEnrollment.plan), joinedload(BenefitEnrollment.employee)
        )
        .filter(BenefitEnrollment.id == enrollment_id)
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    if e.coverage_end is None:
        raise HTTPException(
            status_code=400,
            detail="Enrollment is still active — end it first (the qualifying event)",
        )
    if e.plan.kind != BenefitKind.MEDICAL:
        raise HTTPException(
            status_code=400, detail="COBRA notices apply to medical plans"
        )

    full_premium = float(e.plan.monthly_premium_employee or 0) + float(
        e.plan.monthly_premium_employer or 0
    )
    data = {
        "employee_name": e.employee.full_name if e.employee else "",
        "plan_name": e.plan.name,
        "carrier_name": e.plan.carrier_name,
        "qualifying_event_date": e.coverage_end.isoformat(),
        "election_deadline_days": 60,
        "monthly_premium": round(full_premium * 1.02, 2),
        "full_premium": round(full_premium, 2),
    }
    company = _company_for_pdf(db)
    audit = _hash_and_audit(db, "cobra", f"enr{enrollment_id}", company, data)
    template = _jinja_env.get_template("cobra_notice.html")
    html_str = template.render(data=data, company=company, audit=audit)
    pdf = HTML(string=html_str, url_fetcher=_safe_url_fetcher).write_pdf()
    return _pdf_response(pdf, f"cobra_notice_enr{enrollment_id}.pdf")
