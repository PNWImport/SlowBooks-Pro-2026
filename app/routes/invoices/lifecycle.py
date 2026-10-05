from datetime import date, timedelta
from decimal import Decimal

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.schemas.common import Money, StrictModel
from typing import Optional
from sqlalchemy.exc import IntegrityError
from app.schemas.credit_memos import CreditMemoResponse
from datetime import date as dt_date
from app.database import get_db
from app.models.accounts import Account
from app.models.invoices import Invoice, InvoiceLine, InvoiceStatus
from app.models.items import Item
from app.schemas.invoices import InvoiceResponse, ZeroTotalConfirmation
from app.services.accounting import (
    create_journal_entry,
    reversing_lines,
    get_ar_account_id,
    _q,
)
from app.services.numbering import next_invoice_number
from app.services.settings_service import get_all_settings as get_settings
from app.services.closing_date import check_closing_date
from app.services.control_accounts import MissingControlAccount

from app.routes.invoices._router import router
from app.routes.invoices.helpers import _due_date_from_terms
from app.services.donor_documents import document_label
from app.services.terminology import document_reference, terms_from_db


@router.post("/{invoice_id}/void", response_model=InvoiceResponse)
def void_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Void — creates a reversing journal entry."""
    invoice = (
        db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == InvoiceStatus.VOID:
        raise HTTPException(status_code=400, detail="Invoice already voided")
    # Voiding an invoice with payments applied would reverse the full A/R
    # while the payment's cash-receipt JE + allocations stay on the books —
    # double-counting cash and reversing A/R twice. Require the payment(s)
    # to be voided first so the ledger stays consistent.
    if (invoice.amount_paid or Decimal("0")) > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot void an invoice with payments applied. Void the "
                "payment(s) first, then void the invoice."
            ),
        )
    check_closing_date(db, invoice.date)

    # An invoice or sales receipt the QuickBooks Online import created has
    # no posting of its own: the ledger import's posting for it is reversed
    # instead (none if that import never ran, as in 2.17). When that posting
    # carried the cost of its stock, the stock goes back without a cost
    # entry of ours.
    from app.services import qbo_documents

    cost_in_import = qbo_documents.void_invoice_import_posting(
        db, invoice, document_label(invoice, terms_from_db(db)).lower()
    )

    # Create reversing journal entry if original had one
    if invoice.transaction_id:
        from app.models.transactions import TransactionLine

        original_lines = (
            db.query(TransactionLine)
            .filter(TransactionLine.transaction_id == invoice.transaction_id)
            .all()
        )
        reverse_lines = reversing_lines(original_lines)
        if reverse_lines:
            create_journal_entry(
                db,
                invoice.date,
                f"VOID {document_label(invoice, terms_from_db(db))} #{invoice.invoice_number}",
                reverse_lines,
                source_type="invoice_void",
                source_id=invoice.id,
                class_id=invoice.class_id,
                job_id=invoice.job_id,
                reference=invoice.invoice_number,
            )

    # Late fees have separate postings; reverse each on its own posting date
    # so voiding does not leave fee A/R behind or backdate a later fee reversal.
    from app.models.transactions import Transaction

    late_fees = (
        db.query(Transaction)
        .filter(
            Transaction.source_type == "late_fee", Transaction.source_id == invoice.id
        )
        .all()
    )
    for fee in late_fees:
        check_closing_date(db, fee.date)
        fee_lines = reversing_lines(fee.lines)
        if fee_lines:
            create_journal_entry(
                db,
                fee.date,
                f"VOID Late fee - {document_label(invoice, terms_from_db(db))} #{invoice.invoice_number}",
                fee_lines,
                source_type="invoice_void",
                source_id=invoice.id,
                class_id=fee.class_id,
                job_id=fee.job_id,
                reference=invoice.invoice_number,
            )

    from app.services.inventory_hooks import reverse_sale_for_invoice

    reverse_sale_for_invoice(db, invoice, txn_date=invoice.date)

    invoice.status = InvoiceStatus.VOID
    invoice.balance_due = Decimal("0")
    db.commit()
    db.refresh(invoice)
    resp = InvoiceResponse.model_validate(invoice)
    if invoice.customer:
        resp.customer_name = invoice.customer.name
    return resp


@router.post("/{invoice_id}/send", response_model=InvoiceResponse)
def mark_invoice_sent(invoice_id: int, db: Session = Depends(get_db)):
    """Mark the invoice as sent."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != InvoiceStatus.DRAFT:
        raise HTTPException(
            status_code=400, detail="Only draft invoices can be marked as sent"
        )
    invoice.status = InvoiceStatus.SENT
    db.commit()
    db.refresh(invoice)
    resp = InvoiceResponse.model_validate(invoice)
    if invoice.customer:
        resp.customer_name = invoice.customer.name
    return resp


@router.post("/apply-late-fees")
def apply_late_fees(db: Session = Depends(get_db)):
    """Apply late fees to overdue invoices past the grace period."""
    words = terms_from_db(db)
    from app.models.transactions import Transaction

    settings_dict = get_settings(db)

    if settings_dict.get("late_fee_enabled") != "true":
        raise HTTPException(
            status_code=400, detail="Late fees are not enabled in settings"
        )

    rate = Decimal(settings_dict.get("late_fee_rate", "1.5")) / 100
    grace_days = int(settings_dict.get("late_fee_grace_days", "15"))
    today = date.today()

    overdue = (
        db.query(Invoice)
        .filter(
            # DRAFT invoices are unsent — never charge late fees on an
            # invoice the customer hasn't received.
            Invoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.PARTIAL])
        )
        .filter(Invoice.balance_due > 0)
        .filter(Invoice.due_date <= today - timedelta(days=grace_days))
        .all()
    )

    # Ensure Late Fee Income account exists (4800)
    late_fee_account = (
        db.query(Account).filter(Account.account_number == "4800").first()
    )
    if not late_fee_account:
        from app.models.accounts import AccountType as AT

        late_fee_account = Account(
            name="Late Fee Income",
            account_number="4800",
            account_type=AT.INCOME,
            is_system=False,
            balance=Decimal("0"),
        )
        db.add(late_fee_account)
        db.flush()

    try:
        ar_id = get_ar_account_id(db)
    except MissingControlAccount:
        raise HTTPException(
            status_code=400, detail="Accounts Receivable (1100) not found"
        )
    if not ar_id:
        raise HTTPException(
            status_code=400, detail="Accounts Receivable (1100) not found"
        )

    applied = 0
    for inv in overdue:
        # Check if late fee already applied (look for journal entry with source_type=late_fee, source_id=inv.id)
        existing = (
            db.query(Transaction)
            .filter(
                Transaction.source_type == "late_fee",
                Transaction.source_id == inv.id,
            )
            .first()
        )
        if existing:
            continue

        fee_amount = _q(inv.balance_due * rate)
        if fee_amount <= 0:
            continue

        # Create journal entry: DR A/R, CR Late Fee Income
        journal_lines = [
            {
                "account_id": ar_id,
                "debit": fee_amount,
                "credit": Decimal("0"),
                "description": f"Late fee - {document_label(inv, words)} #{inv.invoice_number}",
            },
            {
                "account_id": late_fee_account.id,
                "debit": Decimal("0"),
                "credit": fee_amount,
                "description": f"Late fee - {document_label(inv, words)} #{inv.invoice_number}",
            },
        ]
        create_journal_entry(
            db,
            today,
            f"Late fee - {document_label(inv, words)} #{inv.invoice_number}",
            journal_lines,
            source_type="late_fee",
            source_id=inv.id,
            class_id=inv.class_id,
            job_id=inv.job_id,
        )

        # Update invoice totals (add to subtotal too so total == subtotal + tax_amount)
        inv.subtotal += fee_amount
        inv.total += fee_amount
        inv.balance_due += fee_amount
        applied += 1

    db.commit()
    return {"applied": applied, "total_overdue": len(overdue)}


class WriteOffRequest(StrictModel):
    date: dt_date
    amount: Optional[Money] = None  # default: the whole open balance
    memo: Optional[str] = None


@router.post(
    "/{invoice_id}/write-off", response_model=CreditMemoResponse, status_code=201
)
def write_off_invoice(
    invoice_id: int, data: WriteOffRequest, db: Session = Depends(get_db)
):
    """Forgive an open balance (a pledge that will never be paid): a credit
    memo flagged as a write-off, posting DR Bad Debt Expense / CR A/R and
    applied to the invoice at once, so the A/R subledger, the donor
    statement and the pledge report all agree. Undo it by voiding the
    credit memo."""
    from app.models.credit_memos import (
        CreditApplication,
        CreditMemo,
        CreditMemoLine,
        CreditMemoStatus,
    )
    from app.services.accounting import get_bad_debt_account_id
    from app.services.numbering import next_credit_memo_number

    check_closing_date(db, data.date)
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.status == InvoiceStatus.VOID:
        raise HTTPException(status_code=400, detail="Invoice is void")
    balance = Decimal(str(inv.balance_due or 0))
    if balance <= 0:
        raise HTTPException(
            status_code=400, detail="Nothing to write off — no open balance"
        )
    amount = _q(Decimal(str(data.amount))) if data.amount is not None else balance
    if amount <= 0 or amount > balance:
        raise HTTPException(
            status_code=400, detail="Write-off must be between 0 and the open balance"
        )

    ar_id = get_ar_account_id(db)
    bad_debt_id = get_bad_debt_account_id(db)
    memo = (
        data.memo
        or f"Write-off: {document_label(inv, terms_from_db(db))} #{inv.invoice_number}"
    )
    cm = None
    for _ in range(10):
        cm = CreditMemo(
            memo_number=next_credit_memo_number(db),
            customer_id=inv.customer_id,
            date=data.date,
            original_invoice_id=inv.id,
            subtotal=amount,
            tax_rate=Decimal("0"),
            tax_amount=Decimal("0"),
            total=amount,
            amount_applied=amount,
            balance_remaining=Decimal("0"),
            notes=memo,
            class_id=inv.class_id,
            job_id=inv.job_id,
            status=CreditMemoStatus.APPLIED,
            is_write_off=True,
        )
        db.add(cm)
        try:
            db.flush()
            break
        except IntegrityError as e:
            if "memo_number" not in str(e.orig).lower():
                raise
            db.rollback()
            cm = None
    if cm is None:
        raise HTTPException(
            status_code=503, detail="Could not assign a credit memo number"
        )
    db.add(
        CreditMemoLine(
            credit_memo_id=cm.id,
            description=memo,
            quantity=1,
            rate=amount,
            amount=amount,
            line_order=0,
        )
    )
    txn = create_journal_entry(
        db,
        data.date,
        f"Credit Memo {cm.memo_number} - write-off of "
        + document_reference(
            document_label(inv, terms_from_db(db)), inv.invoice_number
        ),
        [
            {
                "account_id": bad_debt_id,
                "debit": amount,
                "credit": Decimal("0"),
                "description": memo,
            },
            {
                "account_id": ar_id,
                "debit": Decimal("0"),
                "credit": amount,
                "description": memo,
            },
        ],
        source_type="credit_memo",
        source_id=cm.id,
        class_id=inv.class_id,
        job_id=inv.job_id,
    )
    cm.transaction_id = txn.id
    db.add(CreditApplication(credit_memo_id=cm.id, invoice_id=inv.id, amount=amount))
    inv.amount_paid = Decimal(str(inv.amount_paid or 0)) + amount
    inv.balance_due = balance - amount
    inv.status = InvoiceStatus.PAID if inv.balance_due == 0 else InvoiceStatus.PARTIAL
    db.commit()
    db.refresh(cm)
    resp = CreditMemoResponse.model_validate(cm)
    resp.customer_name = inv.customer.name if inv.customer else None
    return resp


@router.post("/{invoice_id}/duplicate", response_model=InvoiceResponse, status_code=201)
def duplicate_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Duplicate — copy the invoice under a new number."""
    words = terms_from_db(db)
    original = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="Invoice not found")

    today = date.today()

    due_date = _due_date_from_terms(today, original.terms)
    # A fresh sale copies document lines, not separately assessed late fees.
    # Line amounts are kept; tax follows the customer as they stand today.
    from app.services.accounting import compute_line_totals, taxed_copy_lines

    copied = taxed_copy_lines(original.lines, original.customer)
    subtotal, tax_amount, total = compute_line_totals(copied, original.tax_rate)

    new_invoice = Invoice(
        invoice_number=next_invoice_number(db),
        customer_id=original.customer_id,
        status=opening_status(total),
        date=today,
        due_date=_due_date_from_terms(today, original.terms),
        terms=original.terms,
        po_number=original.po_number,
        bill_address1=original.bill_address1,
        bill_address2=original.bill_address2,
        bill_city=original.bill_city,
        bill_state=original.bill_state,
        bill_zip=original.bill_zip,
        ship_address1=original.ship_address1,
        ship_address2=original.ship_address2,
        ship_city=original.ship_city,
        ship_state=original.ship_state,
        ship_zip=original.ship_zip,
        subtotal=subtotal,
        tax_rate=original.tax_rate,
        tax_amount=tax_amount,
        total=total,
        balance_due=total,
        is_pledge=original.is_pledge,
        fair_value_amount=original.fair_value_amount,
        fair_value_description=original.fair_value_description,
        notes=original.notes,
        class_id=original.class_id,
        job_id=original.job_id,
    )
    face = document_label(new_invoice, words)
    db.add(new_invoice)
    db.flush()

    for oline, cline in zip(original.lines, copied):
        new_line = InvoiceLine(
            invoice_id=new_invoice.id,
            item_id=oline.item_id,
            description=oline.description,
            quantity=oline.quantity,
            rate=oline.rate,
            amount=_q(Decimal(str(oline.quantity)) * Decimal(str(oline.rate))),
            class_name=oline.class_name,
            class_id=oline.class_id,
            job_id=oline.job_id,
            cost_code_id=oline.cost_code_id,
            is_taxable=cline.is_taxable,
            line_order=oline.line_order,
        )
        db.add(line)
        new_lines.append(line)

    # Journal Entry — mirror what create_invoice does (DR A/R, CR Income per line)
    ar_id = get_ar_account_id(db)
    default_income_id = get_default_income_account_id(db)
    tax_account_id = get_sales_tax_account_id(db)

    if ar_id and default_income_id:
        journal_lines = []
        # Debit A/R for total
        journal_lines.append(
            {
                "account_id": ar_id,
                "debit": Decimal(str(new_invoice.total)),
                "credit": Decimal("0"),
                "description": document_reference(face, new_number),
            }
        )
        # Credit income for each line
        for oline in original.lines:
            line_amount = Decimal(str(oline.amount))
            if line_amount == 0:
                continue
            income_id = default_income_id
            if oline.item_id:
                item = db.query(Item).filter(Item.id == oline.item_id).first()
                if item and item.income_account_id:
                    income_id = item.income_account_id
            journal_lines.append(
                {
                    "account_id": income_id,
                    "debit": Decimal("0"),
                    "credit": line_amount,
                    "description": oline.description or "",
                    "class_id": oline.class_id,
                    "job_id": oline.job_id,
                    "cost_code_id": oline.cost_code_id,
                }
            )
        # Credit sales tax if any
        if new_invoice.tax_amount and new_invoice.tax_amount > 0 and tax_account_id:
            journal_lines.append(
                {
                    "account_id": tax_account_id,
                    "debit": Decimal("0"),
                    "credit": Decimal(str(new_invoice.tax_amount)),
                    "description": "Sales tax",
                }
            )

        customer = original.customer
        txn = create_journal_entry(
            db,
            today,
            document_reference(face, new_number, customer.name if customer else ""),
            journal_lines,
            source_type="invoice",
            source_id=new_invoice.id,
            class_id=new_invoice.class_id,
            job_id=new_invoice.job_id,
            reference=new_number,
        )
        new_invoice.transaction_id = txn.id

    # Phase 11 (audit fix): a duplicated invoice is a FRESH sale, so it
    # must hit the inventory ledger just like create_invoice does.
    db.flush()
    db.refresh(new_invoice)
    post_sale_for_invoice(db, new_invoice, txn_date=today)

    db.commit()
    db.refresh(new_invoice)
    resp = InvoiceResponse.model_validate(new_invoice)
    if new_invoice.customer:
        resp.customer_name = new_invoice.customer.name
    return resp
