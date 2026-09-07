# ============================================================================
# Employees — CRUD, direct-deposit bank accounts, year-to-date totals,
# self-service portal access, and the per-employee HR document vault.
# ============================================================================

import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel as _BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attachments import Attachment
from app.models.bank_accounts import (
    EmployeeBankAccount,
    BankAccountKind,
    DepositType,
)
from app.models.payroll import Employee
from app.routes.attachments import (
    _sanitize_filename,
    _resolve_within,
    STATIC_BASE,
    UPLOAD_BASE,
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
)
from app.routes.payroll import employee_ytd
from app.schemas.hr import EmployeeDocumentResponse
from app.schemas.payroll import (
    EmployeeCreate,
    EmployeeUpdate,
    EmployeeResponse,
    BankAccountCreate,
    BankAccountResponse,
    YTDResponse,
)
from app.services.encryption import encrypt
from app.services.nacha_export import validate_routing_number
from app.services.onboarding import seed_onboarding_tasks
from app.services.upload_limits import read_limited

# Portal tokens get a 1-year hard expiry on top of the 90-day idle window
# enforced in app/routes/portal.py. Hard expiry forces periodic re-issuance
# even for an employee who logs in regularly.
_PORTAL_TOKEN_LIFETIME = timedelta(days=365)


def _mint_portal_token(emp: Employee) -> None:
    """Assign a fresh portal token plus its idle and hard expiry timestamps."""
    now = datetime.now(timezone.utc)
    emp.portal_token = secrets.token_urlsafe(24)
    emp.portal_token_last_used = now
    emp.portal_token_expires_at = now + _PORTAL_TOKEN_LIFETIME


def _iso_utc(dt: datetime | None) -> str | None:
    """Serialize a (possibly naive) timestamp as an ISO-8601 UTC string. SQLite
    drops tzinfo on round-trip; we restore it so API consumers don't have to
    guess what timezone the stored datetime is in."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("", response_model=list[EmployeeResponse])
def list_employees(active_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(Employee)
    if active_only:
        q = q.filter(Employee.is_active == True)  # noqa: E712
    return q.order_by(Employee.last_name, Employee.first_name).all()


@router.get("/{emp_id}", response_model=EmployeeResponse)
def get_employee(emp_id: int, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp


@router.post("", response_model=EmployeeResponse, status_code=201)
def create_employee(data: EmployeeCreate, db: Session = Depends(get_db)):
    emp = Employee(**data.model_dump())
    # Every new hire gets a self-service portal token and an onboarding checklist.
    _mint_portal_token(emp)
    db.add(emp)
    db.flush()
    seed_onboarding_tasks(db, emp.id)
    db.commit()
    db.refresh(emp)
    return emp


@router.put("/{emp_id}", response_model=EmployeeResponse)
def update_employee(emp_id: int, data: EmployeeUpdate, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(emp, key, val)
    db.commit()
    db.refresh(emp)
    return emp


# --- Self-service portal access -------------------------------------------
def _portal_url(request: Request, token: str) -> str:
    """Absolute portal link. The employee opens this in THEIR browser (or
    their phone), so it must carry the host the server is reachable on —
    127.0.0.1 on a desktop install, the LAN address on Server Edition, the
    public name behind a reverse proxy (X-Forwarded-* is honoured through
    request.base_url when the proxy is trusted)."""
    return f"{str(request.base_url).rstrip('/')}/portal/{token}"


@router.get("/{emp_id}/portal-token")
def get_portal_token(request: Request, emp_id: int, db: Session = Depends(get_db)):
    """Return the employee's self-service portal token, minting one if absent."""
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if not emp.portal_token:
        _mint_portal_token(emp)
        db.commit()
    return {
        "employee_id": emp.id,
        "portal_token": emp.portal_token,
        "portal_url": _portal_url(request, emp.portal_token),
        "expires_at": _iso_utc(emp.portal_token_expires_at),
        "last_used_at": _iso_utc(emp.portal_token_last_used),
    }


@router.get("/{emp_id}/everify")
def get_everify(emp_id: int, db: Session = Depends(get_db)):
    """Return the employee's E-Verify case record."""
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {
        "employee_id": emp.id,
        "case_number": emp.everify_case_number,
        "status": emp.everify_status or "not_submitted",
        "submitted_at": _iso_utc(emp.everify_submitted_at),
        "closed_at": _iso_utc(emp.everify_closed_at),
        "notes": emp.everify_notes,
    }


_EVERIFY_STATUSES = {
    "not_submitted",
    "pending",
    "photo_match_required",
    "tnc",
    "employment_authorized",
    "final_non_confirmation",
    "case_closed",
}


@router.put("/{emp_id}/everify")
def update_everify(
    emp_id: int,
    data: dict,
    db: Session = Depends(get_db),
):
    """Record / update an E-Verify case for the employee.

    Pure record-keeping — the actual case is submitted through the
    federal E-Verify portal (or a vendor like Equifax). This endpoint
    just stores what the operator entered there alongside the employee
    so DHS inspections find it in one place.
    """
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    status = (data.get("status") or "").strip().lower() or None
    if status and status not in _EVERIFY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(_EVERIFY_STATUSES)}",
        )

    if "case_number" in data:
        emp.everify_case_number = (data.get("case_number") or "").strip() or None
    if status is not None:
        # Auto-stamp lifecycle timestamps the first time we see each one.
        if status != "not_submitted" and emp.everify_submitted_at is None:
            emp.everify_submitted_at = datetime.now(timezone.utc)
        if status in ("employment_authorized", "final_non_confirmation", "case_closed"):
            if emp.everify_closed_at is None:
                emp.everify_closed_at = datetime.now(timezone.utc)
        emp.everify_status = status
    if "notes" in data:
        emp.everify_notes = (data.get("notes") or "").strip() or None

    db.commit()
    db.refresh(emp)
    return {
        "employee_id": emp.id,
        "case_number": emp.everify_case_number,
        "status": emp.everify_status or "not_submitted",
        "submitted_at": _iso_utc(emp.everify_submitted_at),
        "closed_at": _iso_utc(emp.everify_closed_at),
        "notes": emp.everify_notes,
    }


@router.get("/{emp_id}/portal-access")
def list_portal_access(
    emp_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Recent portal_accesses rows for one employee. Powers the admin
    "who hit my portal page when?" view in the Employee Details modal."""
    from app.models.portal_access import PortalAccess

    if not db.query(Employee).filter(Employee.id == emp_id).first():
        raise HTTPException(status_code=404, detail="Employee not found")
    rows = (
        db.query(PortalAccess)
        .filter(PortalAccess.employee_id == emp_id)
        .order_by(PortalAccess.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "created_at": _iso_utc(r.created_at),
            "ip": r.ip,
            "user_agent": r.user_agent,
            "path": r.path,
            "success": r.success,
        }
        for r in rows
    ]


@router.post("/{emp_id}/portal-token")
def regenerate_portal_token(
    request: Request, emp_id: int, db: Session = Depends(get_db)
):
    """Rotate the portal token (invalidates the previous self-service link)."""
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    _mint_portal_token(emp)
    db.commit()
    return {
        "employee_id": emp.id,
        "portal_token": emp.portal_token,
        "portal_url": _portal_url(request, emp.portal_token),
        "expires_at": _iso_utc(emp.portal_token_expires_at),
    }


# --- Year-to-date ----------------------------------------------------------
@router.get("/{emp_id}/ytd", response_model=YTDResponse)
def get_employee_ytd(
    emp_id: int, year: int = Query(default=None), db: Session = Depends(get_db)
):
    """Year-to-date payroll totals for an employee (exposes the Bug 1 fix)."""
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    year = year or date.today().year
    totals = employee_ytd(db, emp_id, year)
    return YTDResponse(
        employee_id=emp_id,
        year=year,
        gross=float(totals["gross"]),
        federal=float(totals["federal"]),
        state=float(totals["state"]),
        state_other=float(totals["state_other"]),
        local=float(totals["local"]),
        ss=float(totals["ss"]),
        medicare=float(totals["medicare"]),
        pretax_deductions=float(totals["pretax_deductions"]),
        net=float(totals["net"]),
    )


# --- Direct-deposit bank accounts ------------------------------------------
@router.get("/{emp_id}/bank-accounts", response_model=list[BankAccountResponse])
def list_bank_accounts(emp_id: int, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return (
        db.query(EmployeeBankAccount)
        .filter(EmployeeBankAccount.employee_id == emp_id)
        .order_by(EmployeeBankAccount.priority)
        .all()
    )


@router.post(
    "/{emp_id}/bank-accounts", response_model=BankAccountResponse, status_code=201
)
def add_bank_account(
    emp_id: int, data: BankAccountCreate, db: Session = Depends(get_db)
):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    try:
        kind = BankAccountKind(data.account_kind)
        deposit = DepositType(data.deposit_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid value: {e}")

    routing = (data.routing_number or "").strip()
    account = (data.account_number or "").strip()
    # ABA checksum, not just 9-digits — same validation the portal and the
    # NACHA exporter use, so a typo'd routing number is caught at entry.
    if not validate_routing_number(routing):
        raise HTTPException(status_code=400, detail="Invalid routing number")
    if not account.isdigit():
        raise HTTPException(status_code=400, detail="Account number must be numeric")

    ba = EmployeeBankAccount(
        employee_id=emp_id,
        nickname=data.nickname,
        account_kind=kind,
        routing_number_enc=encrypt(routing),
        account_number_enc=encrypt(account),
        account_last_four=account[-4:],
        deposit_type=deposit,
        deposit_value=data.deposit_value,
        priority=data.priority,
    )
    db.add(ba)
    db.commit()
    db.refresh(ba)
    return ba


@router.delete("/{emp_id}/bank-accounts/{ba_id}")
def remove_bank_account(emp_id: int, ba_id: int, db: Session = Depends(get_db)):
    ba = (
        db.query(EmployeeBankAccount)
        .filter(
            EmployeeBankAccount.id == ba_id, EmployeeBankAccount.employee_id == emp_id
        )
        .first()
    )
    if not ba:
        raise HTTPException(status_code=404, detail="Bank account not found")
    db.delete(ba)
    db.commit()
    return {"status": "deleted", "id": ba_id}


# --- HR document vault -----------------------------------------------------
@router.get("/{emp_id}/documents", response_model=list[EmployeeDocumentResponse])
def list_employee_documents(emp_id: int, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return (
        db.query(Attachment)
        .filter(Attachment.employee_id == emp_id)
        .order_by(Attachment.uploaded_at.desc())
        .all()
    )


@router.post(
    "/{emp_id}/documents", response_model=EmployeeDocumentResponse, status_code=201
)
async def upload_employee_document(
    emp_id: int,
    doc_category: str = Form(default="general"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    safe_filename = _sanitize_filename(file.filename or "")
    extension = Path(safe_filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, detail=f"File extension '{extension}' not allowed"
        )
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400, detail=f"MIME type '{file.content_type}' not allowed"
        )

    content = await read_limited(file, label="Import file")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    # "employee" is a static literal and emp_id is an int — safe path segments.
    upload_dir = _resolve_within(UPLOAD_BASE, "employee", str(emp_id))
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = _resolve_within(upload_dir, safe_filename)
    file_path.write_bytes(content)

    doc = Attachment(
        entity_type="employee",
        entity_id=emp_id,
        employee_id=emp_id,
        doc_category=(doc_category or "general")[:50],
        filename=safe_filename,
        file_path=str(file_path.relative_to(STATIC_BASE)),
        mime_type=file.content_type,
        file_size=len(content),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{emp_id}/documents/{doc_id}")
def download_employee_document(emp_id: int, doc_id: int, db: Session = Depends(get_db)):
    doc = (
        db.query(Attachment)
        .filter(Attachment.id == doc_id, Attachment.employee_id == emp_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    full_path = _resolve_within(STATIC_BASE, doc.file_path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File missing from storage")
    return FileResponse(
        str(full_path),
        filename=doc.filename,
        media_type=doc.mime_type or "application/octet-stream",
    )


@router.delete("/{emp_id}/documents/{doc_id}")
def delete_employee_document(emp_id: int, doc_id: int, db: Session = Depends(get_db)):
    doc = (
        db.query(Attachment)
        .filter(Attachment.id == doc_id, Attachment.employee_id == emp_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    db.commit()
    return {"status": "deleted", "id": doc_id}


# --- Termination / offboarding ----------------------------------------------


class TerminateRequest(_BaseModel):
    termination_date: date
    reason: str = "voluntary"  # "voluntary" | "involuntary"
    include_sick_payout: bool = False
    # Payout accrued PTO even when the state does not require it.
    payout_pto: bool | None = None


@router.post("/{emp_id}/terminate")
def terminate_employee(
    emp_id: int, data: TerminateRequest, db: Session = Depends(get_db)
):
    """Offboard an employee.

    Sets the termination fields and deactivates the employee, their
    recurring deductions, and their portal token; resolves the state
    final-paycheck deadline (from the work state + departure reason); and
    computes the accrued-PTO payout. When the state requires payout — or
    the operator asks for it — the payout is staged as a DRAFT off-cycle
    supplemental run for review, exactly like retro pay.

    Deliberately not automated: the final regular paycheck itself. Its
    hours/period depend on the timecard, so the operator runs it normally;
    this endpoint tells them the statutory deadline.
    """
    from decimal import Decimal

    from app.models.deductions import EmployeeDeduction
    from app.services.termination import (
        compute_pto_payout,
        final_paycheck_deadline,
    )

    if data.reason not in ("voluntary", "involuntary"):
        raise HTTPException(
            status_code=400, detail="reason must be voluntary or involuntary"
        )
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if emp.termination_date:
        raise HTTPException(status_code=400, detail="Employee already terminated")

    # Next regular payday, when a pay schedule is attached — resolves the
    # "next payday" deadline shape to a real date.
    next_payday = None
    if emp.pay_schedule_id:
        from app.models.pay_schedules import PaySchedule
        from app.services.pay_schedule_service import upcoming_pay_dates

        sched = (
            db.query(PaySchedule).filter(PaySchedule.id == emp.pay_schedule_id).first()
        )
        if sched:
            dates = upcoming_pay_dates(sched, data.termination_date, count=1)
            if dates:
                next_payday = date.fromisoformat(dates[0]["pay_date"])

    deadline = final_paycheck_deadline(
        emp.work_state, data.reason, data.termination_date, next_payday
    )
    payout = compute_pto_payout(db, emp, include_sick=data.include_sick_payout)

    # State-required payout cannot be declined; otherwise operator's call
    # (default: pay it out — forfeiting accrued time should be explicit).
    wants_payout = data.payout_pto if data.payout_pto is not None else True
    must_payout = deadline["pto_payout_required"]
    do_payout = (must_payout or wants_payout) and payout["total_payout"] > 0

    emp.termination_date = data.termination_date
    emp.termination_reason = data.reason
    emp.is_active = False
    emp.portal_token = None
    emp.portal_token_expires_at = None
    emp.portal_token_last_used = None

    deactivated = (
        db.query(EmployeeDeduction)
        .filter(
            EmployeeDeduction.employee_id == emp_id,
            EmployeeDeduction.is_active.is_(True),
        )
        .update({"is_active": False})
    )

    staged_run_id = None
    if do_payout:
        import json as _json

        from app.models.payroll import PayRun, PayRunStatus, PayRunType, PayStub
        from app.services.payroll_service import calculate_withholdings
        from app.services.state_tax.reciprocity import withholding_state

        amount = Decimal(str(payout["total_payout"]))
        year = data.termination_date.year
        ytd = employee_ytd(db, emp_id, year, before=None)
        result = calculate_withholdings(
            amount,
            pay_frequency=emp.pay_frequency.value if emp.pay_frequency else "biweekly",
            filing_status=emp.filing_status.value if emp.filing_status else "single",
            ytd_gross=ytd["gross"],
            work_state=(emp.work_state or "WA").upper(),
            withholding_state=withholding_state(
                (emp.work_state or "WA").upper(), emp.residence_state
            ),
            work_locality=emp.work_locality,
            residence_locality=emp.residence_locality,
            wc_class_code=emp.wc_class_code,
            supplemental=True,
        )
        run = PayRun(
            period_start=data.termination_date,
            period_end=data.termination_date,
            pay_date=data.termination_date,
            run_type=PayRunType.OFF_CYCLE,
            status=PayRunStatus.DRAFT,
        )
        db.add(run)
        db.flush()
        db.add(
            PayStub(
                pay_run_id=run.id,
                employee_id=emp_id,
                gross_pay=result["gross"],
                federal_tax=result["federal"],
                state_tax=result["state_income"],
                state_other_employee=result["state_other_employee"],
                local_tax=result["local_tax"],
                local_tax_employer=result["local_tax_employer"],
                ss_tax=result["ss"],
                medicare_tax=result["medicare"],
                work_state=(emp.work_state or "WA").upper(),
                work_locality=emp.work_locality,
                net_pay=result["net"],
                employer_ss_tax=result["employer_ss"],
                employer_medicare_tax=result["employer_medicare"],
                futa_tax=result["futa"],
                suta_tax=result["suta"],
                state_other_employer=result["state_other_employer"],
                detail_json=_json.dumps(
                    {k: str(v) for k, v in result["detail"].items()}
                    | {"pto_payout": str(amount)}
                ),
            )
        )
        run.total_gross = result["gross"]
        run.total_taxes = result["total_employee_tax"]
        run.total_employer_taxes = result["total_employer_tax"]
        run.total_net = result["net"]
        staged_run_id = run.id

    db.commit()
    return {
        "employee_id": emp_id,
        "termination_date": data.termination_date.isoformat(),
        "reason": data.reason,
        "final_paycheck": deadline,
        "pto_payout": payout,
        "pto_payout_staged": do_payout,
        "pto_payout_run_id": staged_run_id,
        "deductions_deactivated": deactivated,
        "portal_token_revoked": True,
    }
