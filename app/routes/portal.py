# ============================================================================
# Employee Self-Service Portal — token-accessed, server-rendered HTML pages
# Lets an employee view pay stubs and update their own W-4, address, bank
# accounts, and PTO requests. Access is by per-employee secret token, the
# same pattern as the public invoice-payment page (no login system).
# ============================================================================

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.bank_accounts import BankAccountKind, DepositType, EmployeeBankAccount
from app.models.payroll import Employee, FilingStatus
from app.models.pto import PTOAccrual, PTOPolicy, PTORequest, PTOType
from app.services.encryption import encrypt
from app.services.rate_limit import limiter
from app.services.settings_service import get_all_settings

router = APIRouter(tags=["portal"])

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(autoescape=True, loader=FileSystemLoader(str(TEMPLATE_DIR)))

# Idle window: a token unused for this long is treated as revoked. Sliding
# window — every authenticated request rolls last_used forward.
PORTAL_TOKEN_IDLE_DAYS = 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC. SQLite returns naive timestamps even when
    we wrote them with tzinfo; PostgreSQL returns tz-aware. Normalize so
    comparisons against _now() never raise TypeError."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _get_employee(token: str, db: Session) -> Employee:
    """Resolve a portal token to an active, non-expired employee, or 404.

    Updates `portal_token_last_used` on every successful lookup, implementing
    a 90-day sliding-window idle expiry. Hard expiry is enforced via
    `portal_token_expires_at`, set when the token is minted.
    """
    employee = db.query(Employee).filter(Employee.portal_token == token).first()
    if not employee or not employee.is_active:
        raise HTTPException(status_code=404, detail="Portal not found")

    now = _now()
    if (
        employee.portal_token_expires_at
        and _to_utc(employee.portal_token_expires_at) < now
    ):
        raise HTTPException(status_code=410, detail="Portal token has expired")
    if employee.portal_token_last_used is not None:
        idle_cutoff = now - timedelta(days=PORTAL_TOKEN_IDLE_DAYS)
        if _to_utc(employee.portal_token_last_used) < idle_cutoff:
            raise HTTPException(status_code=410, detail="Portal token has expired")

    employee.portal_token_last_used = now
    db.commit()
    return employee


# Portal pages need a tighter Referrer-Policy than the app default — the token
# is in the URL, and any cross-origin click could otherwise leak it. We add
# per-response headers in _render() so a portal page can never be referred
# from with a URL that contains the token.
_PORTAL_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store, max-age=0",
}


def _branding(db: Session) -> dict:
    """Company name + logo URL for the portal template header.

    The portal is what employees see when they click their pay-stub link;
    branding it with the *employer's* name and logo (not "Slowbooks Pro")
    is what makes it look like an HR portal instead of a generic SaaS.
    """
    settings = get_all_settings(db)
    return {
        "company_name": settings.get("company_name") or "Employer",
        "company_logo_url": settings.get("company_logo_path") or "",
    }


def _render(name: str, db: Session, **ctx) -> HTMLResponse:
    """Render a portal template with no-referrer headers and company branding."""
    template = _jinja_env.get_template(f"portal/{name}")
    return HTMLResponse(
        template.render(**_branding(db), **ctx), headers=_PORTAL_HEADERS
    )


def _portal_redirect(url: str) -> RedirectResponse:
    """Redirect with the same no-referrer + no-store headers as portal pages."""
    return RedirectResponse(url=url, status_code=303, headers=_PORTAL_HEADERS)


def _processed_stub_count(emp: Employee) -> int:
    """Count the employee's pay stubs belonging to a processed pay run."""
    return sum(
        1
        for stub in emp.pay_stubs
        if stub.pay_run and stub.pay_run.status.value == "processed"
    )


@router.get("/portal/{token}")
@limiter.limit("30/minute")
def portal_dashboard(request: Request, token: str, db: Session = Depends(get_db)):
    """Portal home — greeting, employee summary, and navigation."""
    emp = _get_employee(token, db)
    return _render(
        "dashboard.html",
        db,
        token=token,
        emp=emp,
        stub_count=_processed_stub_count(emp),
    )


@router.get("/portal/{token}/paystubs")
@limiter.limit("30/minute")
def portal_paystubs(request: Request, token: str, db: Session = Depends(get_db)):
    """List the employee's pay stubs (newest first), linking to the PDF."""
    emp = _get_employee(token, db)
    stubs = [
        stub
        for stub in emp.pay_stubs
        if stub.pay_run and stub.pay_run.status.value == "processed"
    ]
    stubs.sort(key=lambda s: s.pay_run.pay_date, reverse=True)
    return _render("paystubs.html", db, token=token, emp=emp, stubs=stubs)


@router.get("/portal/{token}/profile")
@limiter.limit("30/minute")
def portal_profile(
    request: Request, token: str, saved: int = 0, db: Session = Depends(get_db)
):
    """Form pre-filled with the employee's W-4 election and mailing address."""
    emp = _get_employee(token, db)
    return _render(
        "profile.html",
        db,
        token=token,
        emp=emp,
        filing_statuses=list(FilingStatus),
        saved=saved,
    )


@router.post("/portal/{token}/profile")
@limiter.limit("10/minute")
def portal_profile_save(
    request: Request,
    token: str,
    filing_status: str = Form(...),
    multiple_jobs: bool = Form(False),
    dependents_amount: float = Form(0),
    other_income_annual: float = Form(0),
    deductions_annual: float = Form(0),
    extra_withholding: float = Form(0),
    address1: str = Form(""),
    address2: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip: str = Form(""),
    db: Session = Depends(get_db),
):
    """Persist the employee's W-4 election and mailing address."""
    emp = _get_employee(token, db)
    try:
        emp.filing_status = FilingStatus(filing_status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filing status")
    emp.multiple_jobs = bool(multiple_jobs)
    emp.dependents_amount = dependents_amount
    emp.other_income_annual = other_income_annual
    emp.deductions_annual = deductions_annual
    emp.extra_withholding = extra_withholding
    emp.address1 = address1 or None
    emp.address2 = address2 or None
    emp.city = city or None
    emp.state = state or None
    emp.zip = zip or None
    db.commit()
    return _portal_redirect(f"/portal/{token}/profile?saved=1")


@router.get("/portal/{token}/bank")
@limiter.limit("30/minute")
def portal_bank(
    request: Request,
    token: str,
    saved: int = 0,
    error: str = "",
    db: Session = Depends(get_db),
):
    """List the employee's bank accounts plus an add-account form."""
    emp = _get_employee(token, db)
    accounts = (
        db.query(EmployeeBankAccount)
        .filter(EmployeeBankAccount.employee_id == emp.id)
        .order_by(EmployeeBankAccount.id)
        .all()
    )
    return _render(
        "bank.html",
        db,
        token=token,
        emp=emp,
        accounts=accounts,
        account_kinds=list(BankAccountKind),
        deposit_types=list(DepositType),
        saved=saved,
        error=error,
    )


@router.post("/portal/{token}/bank")
@limiter.limit("10/minute")
def portal_bank_add(
    request: Request,
    token: str,
    nickname: str = Form(""),
    account_kind: str = Form(...),
    routing_number: str = Form(...),
    account_number: str = Form(...),
    deposit_type: str = Form(...),
    db: Session = Depends(get_db),
):
    """Validate, encrypt, and store a new direct-deposit bank account."""
    emp = _get_employee(token, db)

    routing = routing_number.strip()
    account = account_number.strip()
    if not (routing.isdigit() and len(routing) == 9):
        return _portal_redirect(
            f"/portal/{token}/bank?error=Routing+number+must+be+9+digits"
        )
    if not account.isdigit():
        return _portal_redirect(
            f"/portal/{token}/bank?error=Account+number+must+be+numeric"
        )
    try:
        kind = BankAccountKind(account_kind)
        dtype = DepositType(deposit_type)
    except ValueError:
        return _portal_redirect(f"/portal/{token}/bank?error=Invalid+selection")

    db.add(
        EmployeeBankAccount(
            employee_id=emp.id,
            nickname=nickname or None,
            account_kind=kind,
            routing_number_enc=encrypt(routing),
            account_number_enc=encrypt(account),
            account_last_four=account[-4:],
            deposit_type=dtype,
            is_active=True,
        )
    )
    db.commit()
    return _portal_redirect(f"/portal/{token}/bank?saved=1")


@router.get("/portal/{token}/pto")
@limiter.limit("30/minute")
def portal_pto(
    request: Request, token: str, saved: int = 0, db: Session = Depends(get_db)
):
    """Show PTO balances, existing requests, and a new-request form."""
    emp = _get_employee(token, db)
    accruals = (
        db.query(PTOAccrual, PTOPolicy)
        .join(PTOPolicy, PTOAccrual.policy_id == PTOPolicy.id)
        .filter(PTOAccrual.employee_id == emp.id)
        .order_by(PTOPolicy.name)
        .all()
    )
    requests = (
        db.query(PTORequest)
        .filter(PTORequest.employee_id == emp.id)
        .order_by(PTORequest.start_date.desc())
        .all()
    )
    return _render(
        "pto.html",
        db,
        token=token,
        emp=emp,
        accruals=accruals,
        requests=requests,
        pto_types=list(PTOType),
        saved=saved,
    )


@router.post("/portal/{token}/pto")
@limiter.limit("10/minute")
def portal_pto_request(
    request: Request,
    token: str,
    start_date: str = Form(...),
    end_date: str = Form(...),
    hours: float = Form(0),
    pto_type: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """Create a new PTO request (status defaults to PENDING)."""
    emp = _get_employee(token, db)
    try:
        ptype = PTOType(pto_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid PTO type")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")

    db.add(
        PTORequest(
            employee_id=emp.id,
            start_date=start,
            end_date=end,
            hours=hours,
            pto_type=ptype,
            notes=notes or None,
        )
    )
    db.commit()
    return _portal_redirect(f"/portal/{token}/pto?saved=1")
