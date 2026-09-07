from decimal import Decimal

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.payroll._router import router
from app.routes.payroll.tax_forms import (
    _company_for_pdf,
    _hash_and_audit,
    _pdf_response,
)
from app.services.tax_forms.state_sui import compute_sui, generate_sui_pdf
from app.services.tax_forms.efw2 import generate_efw2


@router.post("/forms/efw2/{year}")
def generate_efw2_file(year: int, db: Session = Depends(get_db)):
    company = _company_for_pdf(db)
    try:
        content, warnings = generate_efw2(db, year, company)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(
        content={
            "year": year,
            "filename": f"W2REPORT_{year}.txt",
            "record_length": 512,
            "warnings": warnings,
            "content": content,
        }
    )


@router.post("/forms/sui/{year}/{quarter}", response_class=Response)
def generate_sui_report(
    year: int,
    quarter: int,
    state: str = Query(default=None, max_length=2),
    db: Session = Depends(get_db),
):
    if quarter not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="quarter must be 1-4")
    data = compute_sui(db, year, quarter, state.upper() if state else None)

    def _plain(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, list):
            return [_plain(v) for v in value]
        if isinstance(value, dict):
            return {k: _plain(v) for k, v in value.items()}
        return value

    return JSONResponse(content=_plain(data), status_code=200)


@router.post("/forms/sui/{year}/{quarter}/pdf", response_class=Response)
def generate_sui_report_pdf(
    year: int,
    quarter: int,
    state: str = Query(default=None, max_length=2),
    db: Session = Depends(get_db),
):
    if quarter not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="quarter must be 1-4")
    st = state.upper() if state else None
    company = _company_for_pdf(db)
    key = f"yr{year}-q{quarter}" + (f"-{st}" if st else "")
    audit = _hash_and_audit(db, "sui", key, company, compute_sui(db, year, quarter, st))
    pdf = generate_sui_pdf(db, year, quarter, st, company, audit=audit)
    return _pdf_response(pdf, f"sui_{year}_q{quarter}{('_' + st) if st else ''}.pdf")
