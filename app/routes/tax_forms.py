# ============================================================================
# Payroll tax forms — 941, 940, W-2 / W-3, state SUI, 1099-NEC / 1096
# ============================================================================

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.contacts import Vendor
from app.models.payroll import Employee
from app.services.tax_forms import form_941, form_940, w2_w3, state_sui, tax_liability
from app.services import form_1099
from app.services.payroll_documents import employer_block
from app.services.request_utils import content_disposition, file_name

router = APIRouter(prefix="/api/tax-forms", tags=["tax-forms"])


def _company(db: Session) -> dict:
    """The company in Settings (not the "My Company" config default)."""
    return employer_block(db)


def _pdf(content: bytes, *name) -> Response:
    """A form's PDF, named for the form and the person it is for
    ("W-2_2026_Lena-Ortiz.pdf", "941_2026_Q3.pdf"). The names used to
    carry internal ids ("w2_2026_emp1.pdf", "1099nec_2026_vendor3.pdf"),
    which told the owner nothing in the Reports folder (2.18.0 gate,
    NEW-6)."""
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(file_name(*name) + ".pdf")},
    )


def _check_quarter(quarter: int):
    if quarter not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="quarter must be 1-4")


# --- Form 941 — quarterly federal -----------------------------------------
@router.get("/941")
def get_941(
    year: int = Query(...), quarter: int = Query(...), db: Session = Depends(get_db)
):
    _check_quarter(quarter)
    return form_941.compute_941(db, year, quarter)


@router.get("/941/pdf")
def get_941_pdf(
    year: int = Query(...), quarter: int = Query(...), db: Session = Depends(get_db)
):
    _check_quarter(quarter)
    pdf = form_941.generate_941_pdf(db, year, quarter, _company(db))
    return _pdf(pdf, "941", year, f"Q{quarter}")


# --- Form 940 — annual FUTA ------------------------------------------------
@router.get("/940")
def get_940(year: int = Query(...), db: Session = Depends(get_db)):
    return form_940.compute_940(db, year)


@router.get("/940/pdf")
def get_940_pdf(year: int = Query(...), db: Session = Depends(get_db)):
    pdf = form_940.generate_940_pdf(db, year, _company(db))
    return _pdf(pdf, "940", year)


# --- W-2 / W-3 -------------------------------------------------------------
@router.get("/w2")
def get_all_w2(year: int = Query(...), db: Session = Depends(get_db)):
    return {
        "year": year,
        "w3": w2_w3.compute_w3(db, year),
        "w2": w2_w3.compute_all_w2(db, year),
    }


@router.get("/w2/{employee_id}")
def get_w2(employee_id: int, year: int = Query(...), db: Session = Depends(get_db)):
    return w2_w3.compute_w2(db, year, employee_id)


@router.get("/w2/{employee_id}/pdf")
def get_w2_pdf(employee_id: int, year: int = Query(...), db: Session = Depends(get_db)):
    pdf = w2_w3.generate_w2_pdf(db, year, employee_id, _company(db))
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    return _pdf(pdf, "W-2", year, emp.full_name if emp else None)


# --- State unemployment ----------------------------------------------------
@router.get("/sui")
def get_sui(
    year: int = Query(...),
    quarter: int = Query(...),
    state: str = Query(default=None),
    db: Session = Depends(get_db),
):
    _check_quarter(quarter)
    return state_sui.compute_sui(db, year, quarter, state)


# --- Quarterly tax liability schedule --------------------------------------
@router.get("/liability")
def get_tax_liability(
    year: int = Query(...), quarter: int = Query(...), db: Session = Depends(get_db)
):
    """What payroll tax is owed for the quarter, and when it is due."""
    _check_quarter(quarter)
    return tax_liability.compute_tax_liability(db, year, quarter)


@router.get("/deposit-schedule")
def get_deposit_schedule(year: int = Query(..., ge=3), db: Session = Depends(get_db)):
    """Monthly-vs-semiweekly depositor classification via the IRS lookback."""
    from app.services.tax_forms import deposit_schedule

    return deposit_schedule.determine_deposit_schedule(db, year)


@router.get("/liability-calendar")
def get_liability_calendar(year: int = Query(..., ge=3), db: Session = Depends(get_db)):
    """Date-sorted calendar of every payroll tax deposit and return due for
    the year: 941 deposits under the determined schedule (with the $100k
    next-day rule and de-minimis warnings), quarterly FUTA deposits, the
    quarterly/annual return filings, and state quarterly amounts."""
    from app.services.tax_forms import deposit_schedule

    return deposit_schedule.liability_calendar(db, year)


@router.get("/1095")
def get_1095(year: int = Query(...), db: Session = Depends(get_db)):
    """ACA 1095 coverage data + 1094 counts, derived from enrollments."""
    from app.services.aca import compute_1095_data

    return compute_1095_data(db, year)


@router.get("/fica-tip-credit")
def get_fica_tip_credit(year: int = Query(...), db: Session = Depends(get_db)):
    """Form 8846 summary — employer FICA on tips above the $5.15/h pin."""
    from app.services.tips import compute_fica_tip_credit

    return compute_fica_tip_credit(db, year)


# --- 1099-NEC / 1096 -------------------------------------------------------
@router.get("/1099")
def get_1099(year: int = Query(...), db: Session = Depends(get_db)):
    return {
        "year": year,
        "transmittal": form_1099.compute_1096(db, year),
        "vendors": form_1099.compute_1099_data(db, year),
    }


@router.get("/1099/fire")
def get_1099_fire(year: int = Query(...), db: Session = Depends(get_db)):
    """IRS Pub 1220 electronic 1099-NEC file (FIRE/IRIS upload format).

    Returns the fixed-width file plus warnings — vendors without a 9-digit
    tax id are skipped and named, and the Transmitter Control Code the IRS
    assigns on FIRE enrollment must be added before upload.
    """
    from app.services.tax_forms.irs1220 import generate_1099_fire

    try:
        content, warnings = generate_1099_fire(db, year, _company(db))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "year": year,
        "filename": f"IRS1099NEC_{year}.txt",
        "record_length": 750,
        "warnings": warnings,
        "content": content,
    }


@router.get("/1099/{vendor_id}/pdf")
def get_1099_pdf(vendor_id: int, year: int = Query(...), db: Session = Depends(get_db)):
    try:
        pdf = form_1099.generate_1099_nec_pdf(db, year, vendor_id, _company(db))
    except ValueError as e:
        # form_1099 raises ValueError for missing or non-1099 vendors; surface
        # as 404 instead of leaking a 500 stack trace to the operator running
        # year-end forms.
        raise HTTPException(status_code=404, detail=str(e))
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    return _pdf(pdf, "1099-NEC", year, vendor.name if vendor else None)


@router.get("/1096/pdf")
def get_1096_pdf(year: int = Query(...), db: Session = Depends(get_db)):
    pdf = form_1099.generate_1096_pdf(db, year, _company(db))
    return _pdf(pdf, "1096", year)
