import logging
from html import escape
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import Depends, HTTPException, Query
from fastapi.responses import Response
from app.schemas.common import StrictModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment
from app.models.contacts import Customer
from app.services.pdf_service import (
    generate_statement_pdf,
    generate_collection_letter_pdf,
)
from app.services.settings_service import get_all_settings as get_settings
from app.routes.reports._router import router

logger = logging.getLogger(__name__)


class CollectionLetterRequest(StrictModel):
    letter_type: str = "30"
    customer_ids: Optional[list[int]] = None
    send_email: bool = False


@router.get("/ar-aging")
def ar_aging(as_of_date: date = Query(default=None), db: Session = Depends(get_db)):
    if not as_of_date:
        as_of_date = date.today()

    invoices = (
        db.query(Invoice)
        .filter(
            Invoice.status.in_(
                [InvoiceStatus.DRAFT, InvoiceStatus.SENT, InvoiceStatus.PARTIAL]
            )
        )
        .filter(Invoice.date <= as_of_date)
        .filter(Invoice.balance_due > 0)
        .all()
    )

    customer_names = {c.id: c.name for c in db.query(Customer.id, Customer.name).all()}

    aging = {}
    for inv in invoices:
        cid = inv.customer_id
        if cid not in aging:
            aging[cid] = {
                "customer_name": customer_names.get(cid, "Unknown"),
                "customer_id": cid,
                "current": Decimal(0),
                "over_30": Decimal(0),
                "over_60": Decimal(0),
                "over_90": Decimal(0),
                "total": Decimal(0),
                "unapplied_credits": Decimal(0),
            }

        days = (as_of_date - inv.due_date).days if inv.due_date else 0
        bal = inv.balance_due
        if days <= 0:
            aging[cid]["current"] += bal
        elif days <= 30:
            aging[cid]["over_30"] += bal
        elif days <= 60:
            aging[cid]["over_60"] += bal
        else:
            aging[cid]["over_90"] += bal
        aging[cid]["total"] += bal

    from app.models.credit_memos import CreditMemo, CreditMemoStatus

    credits = (
        db.query(CreditMemo)
        .filter(CreditMemo.status != CreditMemoStatus.VOID)
        .filter(CreditMemo.date <= as_of_date)
        .filter(CreditMemo.balance_remaining > 0)
        .all()
    )
    for credit in credits:
        cid = credit.customer_id
        if cid not in aging:
            aging[cid] = {
                "customer_name": customer_names.get(cid, "Unknown"),
                "customer_id": cid,
                "current": Decimal(0),
                "over_30": Decimal(0),
                "over_60": Decimal(0),
                "over_90": Decimal(0),
                "total": Decimal(0),
                "unapplied_credits": Decimal(0),
            }
        amount = Decimal(str(credit.balance_remaining))
        aging[cid]["unapplied_credits"] += amount
        aging[cid]["current"] -= amount
        aging[cid]["total"] -= amount

    columns = (
        "current",
        "over_30",
        "over_60",
        "over_90",
        "total",
        "unapplied_credits",
    )
    items = list(aging.values())
    for item in items:
        item.setdefault("unapplied_credits", Decimal(0))
    totals = {"customer_name": "TOTAL", "customer_id": 0}
    for key in columns:
        totals[key] = sum(item[key] for item in items)
    # Convert Decimals to float for JSON
    for item in items:
        for k in columns:
            item[k] = float(item[k])
    for k in columns:
        totals[k] = float(totals[k])

    return {"as_of_date": as_of_date.isoformat(), "items": items, "totals": totals}


@router.get("/income-by-customer")
def income_by_customer(
    start_date: date = Query(default=None),
    end_date: date = Query(default=None),
    db: Session = Depends(get_db),
):
    """Income by Customer report."""
    if not start_date:
        start_date = date(date.today().year, 1, 1)
    if not end_date:
        end_date = date.today()

    invoices = (
        db.query(Invoice)
        .filter(Invoice.date >= start_date, Invoice.date <= end_date)
        .filter(Invoice.status != InvoiceStatus.VOID)
        .all()
    )

    by_customer = {}
    for inv in invoices:
        cid = inv.customer_id
        if cid not in by_customer:
            cname = inv.customer.name if inv.customer else "Unknown"
            by_customer[cid] = {
                "customer_id": cid,
                "customer_name": cname,
                "invoice_count": 0,
                "total_sales": Decimal(0),
                "total_paid": Decimal(0),
                "total_balance": Decimal(0),
            }
        by_customer[cid]["invoice_count"] += 1
        by_customer[cid]["total_sales"] += inv.total
        by_customer[cid]["total_paid"] += inv.amount_paid
        by_customer[cid]["total_balance"] += inv.balance_due

    items = sorted(by_customer.values(), key=lambda x: x["total_sales"], reverse=True)
    grand_sales = sum((i["total_sales"] for i in items), Decimal("0"))
    grand_paid = sum((i["total_paid"] for i in items), Decimal("0"))
    grand_balance = sum((i["total_balance"] for i in items), Decimal("0"))
    for item in items:
        item["total_sales"] = float(item["total_sales"])
        item["total_paid"] = float(item["total_paid"])
        item["total_balance"] = float(item["total_balance"])

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "items": items,
        "total_sales": float(grand_sales),
        "total_paid": float(grand_paid),
        "total_balance": float(grand_balance),
    }


@router.get("/customer-statement/{customer_id}/pdf")
def customer_statement_pdf(
    customer_id: int,
    as_of_date: date = Query(default=None),
    db: Session = Depends(get_db),
):
    """Customer statement PDF."""
    if not as_of_date:
        as_of_date = date.today()

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    invoices = (
        db.query(Invoice)
        .filter(Invoice.customer_id == customer_id)
        .filter(Invoice.status != InvoiceStatus.VOID)
        .filter(Invoice.date <= as_of_date)
        .order_by(Invoice.date)
        .all()
    )

    payments = (
        db.query(Payment)
        .filter(Payment.customer_id == customer_id)
        .filter(Payment.is_voided.isnot(True))
        .filter(Payment.date <= as_of_date)
        .order_by(Payment.date)
        .all()
    )

    company = get_settings(db)
    pdf_bytes = generate_statement_pdf(
        customer, invoices, payments, company, as_of_date
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=Statement_{customer.name}.pdf"
        },
    )


@router.post("/batch-email-statements")
def batch_email_statements(db: Session = Depends(get_db)):
    """Email statements to all customers with overdue invoices."""
    from app.services.email_service import send_email

    settings = get_settings(db)
    as_of_date = date.today()

    overdue_invoices = (
        db.query(Invoice)
        .filter(
            Invoice.status.in_(
                [InvoiceStatus.DRAFT, InvoiceStatus.SENT, InvoiceStatus.PARTIAL]
            )
        )
        .filter(Invoice.balance_due > 0)
        .filter(Invoice.due_date < as_of_date)
        .all()
    )

    # Group by customer
    by_customer = {}
    for inv in overdue_invoices:
        by_customer.setdefault(inv.customer_id, []).append(inv)

    sent = 0
    failed = 0
    errors = []

    for cid, invs in by_customer.items():
        customer = db.query(Customer).filter(Customer.id == cid).first()
        if not customer or not customer.email:
            errors.append(
                f"Customer {customer.name if customer else cid}: no email address"
            )
            failed += 1
            continue

        try:
            payments = (
                db.query(Payment)
                .filter(Payment.customer_id == cid)
                .filter(Payment.is_voided.isnot(True))
                .filter(Payment.date <= as_of_date)
                .order_by(Payment.date)
                .all()
            )
            all_invoices = (
                db.query(Invoice)
                .filter(Invoice.customer_id == cid)
                .filter(Invoice.status != InvoiceStatus.VOID)
                .filter(Invoice.date <= as_of_date)
                .order_by(Invoice.date)
                .all()
            )

            pdf_bytes = generate_statement_pdf(
                customer, all_invoices, payments, settings, as_of_date
            )

            send_email(
                db=db,
                to_email=customer.email,
                subject=f"Account Statement — {settings.get('company_name', 'Our Company')}",
                html_body=f"<p>Dear {escape(customer.name)},</p><p>Please find your account statement attached.</p><p>{escape(settings.get('company_name') or '')}</p>",
                attachment_bytes=pdf_bytes,
                attachment_name=f"Statement_{customer.name}.pdf",
                entity_type="statement",
                entity_id=cid,
            )
            sent += 1
        except Exception:
            logger.exception("Failed to send statement to customer %s", customer.id)
            errors.append(f"Customer {customer.name}: unable to send statement")
            failed += 1

    return {"sent": sent, "failed": failed, "errors": errors}


@router.post("/collection-letters")
def collection_letters(data: CollectionLetterRequest, db: Session = Depends(get_db)):
    """Generate and optionally email collection letters."""
    from app.services.email_service import send_email

    letter_type = data.letter_type
    customer_ids = data.customer_ids
    send_email_flag = data.send_email
    settings = get_settings(db)
    today = date.today()

    # Map letter type to minimum days overdue
    min_days = {"30": 30, "60": 60, "90": 90}.get(letter_type, 30)

    q = (
        db.query(Invoice)
        .filter(
            Invoice.status.in_(
                [InvoiceStatus.DRAFT, InvoiceStatus.SENT, InvoiceStatus.PARTIAL]
            )
        )
        .filter(Invoice.balance_due > 0)
        .filter(Invoice.due_date <= today - timedelta(days=min_days))
    )
    if customer_ids:
        q = q.filter(Invoice.customer_id.in_(customer_ids))

    overdue_invoices = q.all()

    # Group by customer
    by_customer = {}
    for inv in overdue_invoices:
        by_customer.setdefault(inv.customer_id, []).append(inv)

    generated = 0
    emailed = 0
    errors = []

    for cid, invs in by_customer.items():
        customer = db.query(Customer).filter(Customer.id == cid).first()
        if not customer:
            continue

        # Add days_overdue to each invoice for the template
        for inv in invs:
            inv.days_overdue = (today - inv.due_date).days if inv.due_date else 0

        total_due = sum((inv.balance_due for inv in invs), Decimal("0"))

        try:
            pdf_bytes = generate_collection_letter_pdf(
                customer, invs, settings, letter_type, total_due
            )
            generated += 1

            if send_email_flag and customer.email:
                type_labels = {
                    "30": "Payment Reminder",
                    "60": "Second Notice",
                    "90": "Final Notice",
                }
                send_email(
                    db=db,
                    to_email=customer.email,
                    subject=f"{type_labels.get(letter_type, 'Collection Notice')} — {settings.get('company_name', '')}",
                    html_body=f"<p>Dear {escape(customer.name)},</p><p>Please see the attached collection notice regarding your outstanding balance of ${total_due:,.2f}.</p>",
                    attachment_bytes=pdf_bytes,
                    attachment_name=f"Collection_{letter_type}day_{customer.name}.pdf",
                    entity_type="collection",
                    entity_id=cid,
                )
                emailed += 1
        except Exception:
            logger.exception(
                "Failed to generate collection letter for customer %s", customer.id
            )
            errors.append(f"{customer.name}: unable to generate collection letter")

    return {"generated": generated, "emailed": emailed, "errors": errors}
