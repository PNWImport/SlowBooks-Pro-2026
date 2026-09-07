# ============================================================================
# Document auto-numbering — the one home for every "next number" policy.
#
# The four document types previously each carried their own copy of MAX+1
# logic (invoices had two — routes/invoices.py and recurring_service.py).
# The strategies differ only in prefix, starting value, and zero-padding;
# estimates additionally seed from the user-configurable settings counter
# instead of the column MAX.
#
# These helpers only PROPOSE a number. Two concurrent creates can still pick
# the same one; every caller flushes inside a retry-on-IntegrityError loop
# with the column's UNIQUE constraint as the safety net (see create_invoice
# in app/routes/invoices.py for the canonical pattern).
# ============================================================================

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.credit_memos import CreditMemo
from app.models.estimates import Estimate
from app.models.invoices import Invoice
from app.models.purchase_orders import PurchaseOrder
from app.services.settings_service import get_all_settings


def next_document_number(
    db: Session,
    column,
    *,
    prefix: str = "",
    first: int = 1001,
    pad: int = 0,
    seed: int | None = None,
) -> str:
    """Return the next unused number for `column` as a string.

    Starts from `seed` if given, otherwise from MAX(column)+1 when the
    current MAX is shaped like prefix+digits, otherwise from `first`.
    The candidate is collision-checked and bumped until free.

    `pad` zero-pads the numeric part; 0 means "match the width of the
    current MAX", which preserves zfill behavior for plain numeric series
    (invoice "0099" -> "0100").
    """
    n = None
    if seed is not None:
        n = seed
    else:
        last = db.query(sqlfunc.max(column)).scalar()
        if last and last.startswith(prefix):
            digits = last[len(prefix) :]
            if digits.isdigit():
                n = int(digits) + 1
                if not pad:
                    pad = len(digits)
    if n is None:
        n = first
    while True:
        candidate = f"{prefix}{str(n).zfill(pad)}"
        if db.query(column).filter(column == candidate).first() is None:
            return candidate
        n += 1


def next_invoice_number(db: Session) -> str:
    return next_document_number(db, Invoice.invoice_number)


def next_credit_memo_number(db: Session) -> str:
    return next_document_number(
        db, CreditMemo.memo_number, prefix="CM-", first=1, pad=4
    )


def next_po_number(db: Session) -> str:
    return next_document_number(
        db, PurchaseOrder.po_number, prefix="PO-", first=1, pad=4
    )


def next_estimate_number(db: Session) -> str:
    """Estimates seed from the user-configurable settings counter."""
    settings = get_all_settings(db)
    prefix = settings.get("estimate_prefix", "E-")
    raw = (settings.get("estimate_next_number", "1001") or "1001").strip() or "1001"
    try:
        seed = int(raw)
    except ValueError:
        seed = 1001
    return next_document_number(db, Estimate.estimate_number, prefix=prefix, seed=seed)
