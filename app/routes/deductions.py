# ============================================================================
# Garnishment orders. Voluntary deductions and benefits live in the benefits
# engine (app/routes/benefits.py).
# ============================================================================

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.payroll import Employee
from app.models.deductions import (
    GarnishmentOrder,
    GarnishmentType,
    GarnishmentMethod,
)
from app.schemas.common import StrictModel
from app.schemas.deductions import (
    GarnishmentOrderCreate,
    GarnishmentOrderResponse,
)

router = APIRouter(prefix="/api/deductions", tags=["deductions"])


# --- Garnishment orders ----------------------------------------------------
@router.get("/garnishments", response_model=list[GarnishmentOrderResponse])
def list_garnishments(
    employee_id: int = Query(default=None), db: Session = Depends(get_db)
):
    q = db.query(GarnishmentOrder)
    if employee_id:
        q = q.filter(GarnishmentOrder.employee_id == employee_id)
    return q.order_by(GarnishmentOrder.priority).all()


@router.post("/garnishments", response_model=GarnishmentOrderResponse, status_code=201)
def create_garnishment(data: GarnishmentOrderCreate, db: Session = Depends(get_db)):
    if not db.query(Employee).filter(Employee.id == data.employee_id).first():
        raise HTTPException(status_code=404, detail="Employee not found")
    try:
        gtype = GarnishmentType(data.garnishment_type)
        method = GarnishmentMethod(data.calc_method)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid value: {e}")
    order = GarnishmentOrder(
        employee_id=data.employee_id,
        garnishment_type=gtype,
        calc_method=method,
        amount=data.amount,
        priority=data.priority,
        case_number=data.case_number,
        agency_name=data.agency_name,
        agency_address=data.agency_address,
        remit_reference=data.remit_reference,
        supports_secondary_family=data.supports_secondary_family,
        in_arrears_12_weeks=data.in_arrears_12_weeks,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.delete("/garnishments/{order_id}")
def remove_garnishment(order_id: int, db: Session = Depends(get_db)):
    order = db.query(GarnishmentOrder).filter(GarnishmentOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Garnishment order not found")
    db.delete(order)
    db.commit()
    return {"status": "deleted", "id": order_id}


# --- Garnishment remittance register ----------------------------------------


@router.get("/garnishments/remittances")
def list_remittances(
    status: str = Query(default="pending"),
    db: Session = Depends(get_db),
):
    """The remittance register: what withheld garnishment money still owes
    an agency a payment. ?status=pending|remitted|all."""
    from app.models.deductions import GarnishmentRemittance

    q = db.query(GarnishmentRemittance).order_by(
        GarnishmentRemittance.withheld_date, GarnishmentRemittance.id
    )
    if status == "pending":
        q = q.filter(GarnishmentRemittance.remitted_at.is_(None))
    elif status == "remitted":
        q = q.filter(GarnishmentRemittance.remitted_at.isnot(None))
    elif status != "all":
        raise HTTPException(
            status_code=400, detail="status must be pending, remitted, or all"
        )
    rows = q.all()

    total_pending = sum(
        (Decimal(str(r.amount or 0)) for r in rows if r.remitted_at is None),
        Decimal("0"),
    )
    return {
        "total_pending": float(total_pending),
        "rows": [
            {
                "id": r.id,
                "order_id": r.order_id,
                "pay_run_id": r.pay_run_id,
                "employee_id": r.employee_id,
                "employee_name": r.employee.full_name if r.employee else None,
                "garnishment_type": (
                    r.order.garnishment_type.value if r.order else None
                ),
                "agency_name": r.order.agency_name if r.order else None,
                "agency_missing": bool(r.order and not r.order.agency_name),
                "remit_reference": r.order.remit_reference if r.order else None,
                "case_number": r.order.case_number if r.order else None,
                "amount": float(r.amount or 0),
                "withheld_date": r.withheld_date.isoformat(),
                "remitted_at": (r.remitted_at.isoformat() if r.remitted_at else None),
                "remit_payment_reference": r.remit_payment_reference,
            }
            for r in rows
        ],
    }


class MarkRemittedRequest(StrictModel):
    payment_reference: str


@router.post("/garnishments/remittances/{remittance_id}/mark-remitted")
def mark_remitted(
    remittance_id: int, data: MarkRemittedRequest, db: Session = Depends(get_db)
):
    """Record that the withheld money actually went out the door."""
    from datetime import datetime, timezone

    from app.models.deductions import GarnishmentRemittance

    row = (
        db.query(GarnishmentRemittance)
        .filter(GarnishmentRemittance.id == remittance_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Remittance not found")
    if row.remitted_at is not None:
        raise HTTPException(status_code=400, detail="Already marked remitted")
    row.remitted_at = datetime.now(timezone.utc)
    row.remit_payment_reference = data.payment_reference
    db.commit()
    return {"id": row.id, "remitted_at": row.remitted_at.isoformat()}
