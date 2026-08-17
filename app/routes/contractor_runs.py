# ============================================================================
# Contractor pay runs — batch-paying 1099 contractors, payroll-style.
# ----------------------------------------------------------------------------
# One dated run, many payees, one JE (DR contractor expense, CR bank), one
# NACHA file. No withholding — 1099 payees get gross. Payments here join
# bill payments in the 1099-NEC totals (services/form_1099.py).
# ============================================================================

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from typing import Optional

from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session, joinedload

from app import config
from app.database import get_db
from app.models.accounts import Account
from app.models.bank_accounts import BankAccountKind
from app.models.contacts import Vendor
from app.models.contractor_payments import (
    ContractorPayment,
    ContractorPayRun,
    ContractorRunStatus,
    VendorBankAccount,
)
from app.services.accounting import create_journal_entry
from app.services.encryption import encrypt

router = APIRouter(prefix="/api/contractor-runs", tags=["contractor-runs"])

CENT = Decimal("0.01")


# --- schemas ----------------------------------------------------------------


class ContractorPaymentInput(BaseModel):
    vendor_id: int
    amount: float
    description: Optional[str] = None

    @model_validator(mode="after")
    def _positive(self):
        if self.amount is None or self.amount <= 0:
            raise ValueError("amount must be positive")
        return self


class ContractorRunCreate(BaseModel):
    pay_date: date
    memo: Optional[str] = None
    payments: list[ContractorPaymentInput] = []


class VendorBankCreate(BaseModel):
    routing_number: str
    account_number: str
    account_kind: str = "checking"
    nickname: Optional[str] = None


class NachaOriginating(BaseModel):
    immediate_destination: str
    immediate_origin: str
    destination_name: str = "BANK"
    origin_name: str = ""
    company_name: str = ""
    company_id: str = ""
    originating_dfi_id: str
    company_account: str = ""
    effective_date: Optional[date] = None


def _run_response(run: ContractorPayRun) -> dict:
    return {
        "id": run.id,
        "pay_date": run.pay_date.isoformat(),
        "memo": run.memo,
        "status": run.status.value if run.status else None,
        "total_amount": float(run.total_amount or 0),
        "transaction_id": run.transaction_id,
        "payments": [
            {
                "id": p.id,
                "vendor_id": p.vendor_id,
                "vendor_name": p.vendor.name if p.vendor else None,
                "amount": float(p.amount or 0),
                "description": p.description,
            }
            for p in run.payments
        ],
    }


# --- runs -------------------------------------------------------------------


@router.get("")
def list_runs(db: Session = Depends(get_db)):
    runs = (
        db.query(ContractorPayRun)
        .options(
            joinedload(ContractorPayRun.payments).joinedload(ContractorPayment.vendor)
        )
        .order_by(ContractorPayRun.pay_date.desc())
        .all()
    )
    return [_run_response(r) for r in runs]


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = (
        db.query(ContractorPayRun)
        .options(
            joinedload(ContractorPayRun.payments).joinedload(ContractorPayment.vendor)
        )
        .filter(ContractorPayRun.id == run_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Contractor run not found")
    return _run_response(run)


@router.post("", status_code=201)
def create_run(data: ContractorRunCreate, db: Session = Depends(get_db)):
    if not data.payments:
        raise HTTPException(status_code=400, detail="At least one payment required")

    total = Decimal("0")
    run = ContractorPayRun(pay_date=data.pay_date, memo=data.memo)
    db.add(run)
    db.flush()

    for p in data.payments:
        vendor = db.query(Vendor).filter(Vendor.id == p.vendor_id).first()
        if not vendor:
            raise HTTPException(
                status_code=404, detail=f"Vendor {p.vendor_id} not found"
            )
        amount = Decimal(str(p.amount)).quantize(CENT)
        db.add(
            ContractorPayment(
                run_id=run.id,
                vendor_id=p.vendor_id,
                amount=amount,
                description=p.description,
            )
        )
        total += amount

    run.total_amount = total
    db.commit()
    db.refresh(run)
    return _run_response(run)


@router.post("/{run_id}/process")
def process_run(run_id: int, db: Session = Depends(get_db)):
    """Post the JE: DR contractor/subcontractor expense, CR bank."""
    from app.services.closing_date import check_closing_date

    run = (
        db.query(ContractorPayRun)
        .options(joinedload(ContractorPayRun.payments))
        .filter(ContractorPayRun.id == run_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Contractor run not found")
    if run.status == ContractorRunStatus.PROCESSED:
        raise HTTPException(status_code=400, detail="Run already processed")
    if run.status == ContractorRunStatus.VOID:
        raise HTTPException(status_code=400, detail="Run is void")
    check_closing_date(db, run.pay_date)

    def _acct(num, fallback=None):
        a = db.query(Account).filter(Account.account_number == num).first()
        if a:
            return a.id
        if fallback:
            return _acct(fallback)
        return None

    # 6130 Contractor/Subcontractor expense, falling back to generic expense.
    expense = _acct("6130", "6000")
    bank = _acct("1000")
    if not expense or not bank:
        raise HTTPException(
            status_code=400,
            detail="Required accounts not found (need 6130/6000 and 1000).",
        )

    total = sum((Decimal(str(p.amount or 0)) for p in run.payments), Decimal("0"))
    if total <= 0:
        raise HTTPException(status_code=400, detail="Run total must be positive")

    txn = create_journal_entry(
        db,
        run.pay_date,
        f"Contractor payments {run.pay_date}" + (f" — {run.memo}" if run.memo else ""),
        [
            {
                "account_id": expense,
                "debit": total,
                "credit": Decimal("0"),
                "description": "Contractor payments",
            },
            {
                "account_id": bank,
                "debit": Decimal("0"),
                "credit": total,
                "description": "Contractor payments",
            },
        ],
        source_type="contractor_run",
        source_id=run.id,
    )
    run.transaction_id = txn.id
    run.status = ContractorRunStatus.PROCESSED
    db.commit()
    return {
        "status": "processed",
        "contractor_run_id": run.id,
        "transaction_id": txn.id,
    }


@router.post("/{run_id}/nacha", response_class=PlainTextResponse)
def export_contractor_nacha(
    run_id: int, originating: NachaOriginating, db: Session = Depends(get_db)
):
    """NACHA ACH file crediting each contractor's bank account."""
    from app.services.nacha_export import generate_contractor_nacha_file

    run = db.query(ContractorPayRun).filter(ContractorPayRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Contractor run not found")
    if run.status != ContractorRunStatus.PROCESSED:
        raise HTTPException(
            status_code=400, detail="Run must be processed before ACH export"
        )

    orig = originating.model_dump()
    if not orig.get("effective_date"):
        orig["effective_date"] = run.pay_date
    if not orig.get("company_name"):
        orig["company_name"] = config.COMPANY_NAME
    if not orig.get("company_id"):
        orig["company_id"] = config.EMPLOYER_EIN
    return generate_contractor_nacha_file(db, run_id, orig)


# --- vendor bank accounts ---------------------------------------------------


@router.get("/vendors/{vendor_id}/bank")
def list_vendor_bank(vendor_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(VendorBankAccount)
        .filter(VendorBankAccount.vendor_id == vendor_id)
        .all()
    )
    return [
        {
            "id": r.id,
            "nickname": r.nickname,
            "account_kind": r.account_kind.value if r.account_kind else None,
            "account_last_four": r.account_last_four,
            "is_active": bool(r.is_active),
        }
        for r in rows
    ]


@router.post("/vendors/{vendor_id}/bank", status_code=201)
def add_vendor_bank(
    vendor_id: int, data: VendorBankCreate, db: Session = Depends(get_db)
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    try:
        kind = BankAccountKind(data.account_kind)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account kind")

    routing = (data.routing_number or "").strip()
    account = (data.account_number or "").strip()
    if not routing.isdigit() or len(routing) != 9:
        raise HTTPException(status_code=400, detail="Routing number must be 9 digits")
    if not account.isdigit():
        raise HTTPException(status_code=400, detail="Account number must be numeric")

    # One active account per vendor: adding a new one supersedes the old.
    db.query(VendorBankAccount).filter(
        VendorBankAccount.vendor_id == vendor_id,
        VendorBankAccount.is_active.is_(True),
    ).update({"is_active": False})

    row = VendorBankAccount(
        vendor_id=vendor_id,
        nickname=data.nickname,
        account_kind=kind,
        routing_number_enc=encrypt(routing),
        account_number_enc=encrypt(account),
        account_last_four=account[-4:],
        is_active=True,
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "account_last_four": row.account_last_four}
