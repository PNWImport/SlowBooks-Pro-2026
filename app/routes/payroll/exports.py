from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response, PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.payroll._router import router
from app.routes.payroll.ach import AchOriginating
from app.services import ach_settings
from app.routes.payroll.ytd import employee_ytd
from app.models.payroll import (
    PayRun,
    PayStub,
    PayRunStatus,
    Employee,
)
from app.services.settings_service import company_identity


@router.get("/{run_id}/paystub/{stub_id}")
def download_paystub(run_id: int, stub_id: int, db: Session = Depends(get_db)):
    """Generate the PDF pay stub for one employee on a pay run."""
    from app.services.paystub_pdf import generate_paystub_pdf

    stub = (
        db.query(PayStub)
        .filter(PayStub.id == stub_id, PayStub.pay_run_id == run_id)
        .first()
    )
    if not stub:
        raise HTTPException(status_code=404, detail="Pay stub not found")
    run = db.query(PayRun).filter(PayRun.id == run_id).first()
    emp = db.query(Employee).filter(Employee.id == stub.employee_id).first()

    ytd = employee_ytd(db, stub.employee_id, run.pay_date.year)
    company = company_identity(db)
    pdf = generate_paystub_pdf(
        stub, emp, run, company, {k: str(v) for k, v in ytd.items()}
    )
    filename = f"paystub_{run_id}_{stub_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


@router.post("/{run_id}/nacha", response_class=PlainTextResponse)
def export_nacha(
    run_id: int,
    originating: AchOriginating,
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate a NACHA ACH file for direct deposit of a processed pay run."""
    from app.services.nacha_export import generate_nacha_file

    run = db.query(PayRun).filter(PayRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Pay run not found")
    if run.status != PayRunStatus.PROCESSED:
        raise HTTPException(
            status_code=400, detail="Pay run must be processed before ACH export"
        )
    orig = ach_settings.originating_for_export(
        request, db, originating.model_dump(), run.pay_date
    )
    try:
        nacha = generate_nacha_file(db, run_id, orig)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ach_settings.record_export(db, "pay_runs", run_id)
    return PlainTextResponse(
        content=nacha,
        headers={"Content-Disposition": f"attachment; filename=payroll_{run_id}.ach"},
    )
