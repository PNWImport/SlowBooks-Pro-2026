# ============================================================================
# Deposit Recording — Move funds from Undeposited Funds to bank account
# Classic QB "Make Deposits" workflow
# ============================================================================

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.transactions import Transaction, TransactionLine
from app.models.accounts import Account
from app.schemas.deposits import DepositCreate, PendingDepositResponse
from app.services.accounting import create_journal_entry, get_undeposited_funds_id
from app.services.closing_date import check_closing_date

router = APIRouter(prefix="/api/deposits", tags=["deposits"])


@router.get("/pending", response_model=list[PendingDepositResponse])
def list_pending_deposits(db: Session = Depends(get_db)):
    """Get payments sitting in Undeposited Funds (1200) — debit entries."""
    uf_id = get_undeposited_funds_id(db)
    if not uf_id:
        return []

    # Find all debit entries to Undeposited Funds
    lines = (
        db.query(TransactionLine, Transaction)
        .join(Transaction, TransactionLine.transaction_id == Transaction.id)
        .filter(TransactionLine.account_id == uf_id)
        .filter(TransactionLine.debit > 0)
        .order_by(Transaction.date.desc())
        .all()
    )

    # Also find credits (deposits already made) to exclude net-zero items
    credit_lines = (
        db.query(TransactionLine)
        .filter(TransactionLine.account_id == uf_id)
        .filter(TransactionLine.credit > 0)
        .all()
    )
    total_credits = sum(cl.credit for cl in credit_lines)
    total_debits = sum(tl.debit for tl, _ in lines)

    # If all deposited, nothing pending
    if total_credits >= total_debits:
        return []

    results = []
    running_credit = total_credits
    for tl, txn in lines:
        pending_amount = tl.debit
        if running_credit > 0:
            applied = min(running_credit, pending_amount)
            running_credit -= applied
            pending_amount -= applied
        if pending_amount <= 0:
            continue
        results.append(
            PendingDepositResponse(
                transaction_line_id=tl.id,
                transaction_id=txn.id,
                date=txn.date,
                description=txn.description or "",
                reference=txn.reference or "",
                source_type=txn.source_type or "",
                amount=float(pending_amount),
            )
        )

    return results


@router.post("")
def create_deposit(data: DepositCreate, db: Session = Depends(get_db)):
    check_closing_date(db, data.date)

    bank_account = (
        db.query(Account).filter(Account.id == data.deposit_to_account_id).first()
    )
    if not bank_account:
        raise HTTPException(status_code=404, detail="Bank account not found")

    uf_id = get_undeposited_funds_id(db)
    if not uf_id:
        raise HTTPException(
            status_code=400, detail="Undeposited Funds account not found"
        )

    # Serialize the availability check across deposits. Without this, two
    # workers can both observe the same pending cash and credit account 1200
    # twice. The account-row lock is portable to PostgreSQL; SQLite's write
    # serialization still protects its single-file runtime.
    db.query(Account).filter(Account.id == uf_id).with_for_update().one()

    total = Decimal(str(data.total))
    if total <= 0:
        raise HTTPException(status_code=400, detail="Deposit amount must be positive")
    uf_lines = db.query(TransactionLine).filter(TransactionLine.account_id == uf_id)
    available = sum(
        (
            Decimal(str(line.debit or 0)) - Decimal(str(line.credit or 0))
            for line in uf_lines
        ),
        Decimal("0"),
    )
    if total > available:
        raise HTTPException(
            status_code=400,
            detail=f"Deposit exceeds pending Undeposited Funds balance of ${available:.2f}",
        )

    journal_lines = [
        {
            "account_id": data.deposit_to_account_id,
            "debit": total,
            "credit": Decimal("0"),
            "description": f"Deposit to {bank_account.name}",
        },
        {
            "account_id": uf_id,
            "debit": Decimal("0"),
            "credit": total,
            "description": f"Deposit to {bank_account.name}",
        },
    ]

    txn = create_journal_entry(
        db,
        data.date,
        f"Deposit to {bank_account.name}",
        journal_lines,
        source_type="deposit",
        reference=data.reference or "",
        class_id=data.class_id,
        job_id=data.job_id,
    )

    db.commit()
    return {"status": "ok", "transaction_id": txn.id, "amount": float(total)}
