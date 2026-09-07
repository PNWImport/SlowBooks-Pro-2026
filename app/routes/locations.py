# ============================================================================
# Work locations — CRUD + employee assignment.
# ============================================================================

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.locations import WorkLocation
from app.models.payroll import Employee
from app.services.local_tax import get_locality
from app.services.state_tax import is_supported, list_states

router = APIRouter(prefix="/api/locations", tags=["locations"])


class LocationCreate(BaseModel):
    name: str
    state: str
    address1: Optional[str] = None
    address2: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    locality: Optional[str] = None
    default_wc_class_code: Optional[str] = None


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    state: Optional[str] = None
    address1: Optional[str] = None
    address2: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    locality: Optional[str] = None
    default_wc_class_code: Optional[str] = None
    is_active: Optional[bool] = None


def _response(loc: WorkLocation) -> dict:
    return {
        "id": loc.id,
        "name": loc.name,
        "address1": loc.address1,
        "address2": loc.address2,
        "city": loc.city,
        "state": loc.state,
        "zip": loc.zip,
        "locality": loc.locality,
        "default_wc_class_code": loc.default_wc_class_code,
        "is_active": bool(loc.is_active),
    }


def _validate_jurisdiction(state: str | None, locality: str | None):
    if state is not None:
        state = state.strip().upper()
        if not is_supported(state):
            raise HTTPException(status_code=400, detail=f"Unknown state {state!r}")
    if locality and get_locality(locality) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown locality code {locality!r} — see "
            "app/services/local_tax/localities/",
        )
    return state


@router.get("")
def list_locations(db: Session = Depends(get_db)):
    rows = db.query(WorkLocation).order_by(WorkLocation.name).all()
    return [_response(r) for r in rows]


@router.post("", status_code=201)
def create_location(data: LocationCreate, db: Session = Depends(get_db)):
    state = _validate_jurisdiction(data.state, data.locality)
    if db.query(WorkLocation).filter(WorkLocation.name == data.name).first():
        raise HTTPException(status_code=400, detail="Location name already exists")
    loc = WorkLocation(
        name=data.name,
        state=state,
        address1=data.address1,
        address2=data.address2,
        city=data.city,
        zip=data.zip,
        locality=(data.locality or None),
        default_wc_class_code=data.default_wc_class_code,
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return _response(loc)


@router.put("/{location_id}")
def update_location(
    location_id: int, data: LocationUpdate, db: Session = Depends(get_db)
):
    loc = db.query(WorkLocation).filter(WorkLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    state = _validate_jurisdiction(data.state, data.locality)
    if data.name is not None:
        loc.name = data.name
    if state is not None:
        loc.state = state
    for field in (
        "address1",
        "address2",
        "city",
        "zip",
        "locality",
        "default_wc_class_code",
        "is_active",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(loc, field, value)
    db.commit()
    return _response(loc)


@router.post("/{location_id}/assign/{emp_id}")
def assign_employee(location_id: int, emp_id: int, db: Session = Depends(get_db)):
    """Attach an employee to a location. Explicit per-employee work_state /
    work_locality keep precedence; the location fills the gaps."""
    loc = db.query(WorkLocation).filter(WorkLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    emp.location_id = loc.id
    db.commit()
    return {"employee_id": emp_id, "location_id": loc.id}


@router.get("/{location_id}/employees")
def location_employees(location_id: int, db: Session = Depends(get_db)):
    if not db.query(WorkLocation).filter(WorkLocation.id == location_id).first():
        raise HTTPException(status_code=404, detail="Location not found")
    rows = db.query(Employee).filter(Employee.location_id == location_id).all()
    return [
        {"id": e.id, "name": e.full_name, "is_active": bool(e.is_active)} for e in rows
    ]
