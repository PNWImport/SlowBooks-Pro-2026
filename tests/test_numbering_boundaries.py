"""Document numbering strategy and collision boundaries."""

from app.models.invoices import Invoice
from app.services import numbering


class _Query:
    def __init__(self, value=None, occupied=None):
        self.value = value
        self.occupied = set(occupied or ())

    def scalar(self):
        return self.value

    def filter(self, *_args):
        expression = _args[0]
        self.value = getattr(getattr(expression, "right", None), "value", self.value)
        return self

    def first(self):
        return object() if self.value in self.occupied else None


class _DB:
    def __init__(self, last=None, occupied=()):
        self.last = last
        self.occupied = set(occupied)

    def query(self, expression):
        if expression is Invoice.invoice_number:
            return _Query(self.last, self.occupied)
        return _Query(self.last)


def test_numbering_seed_shapes_padding_and_collision():
    assert (
        numbering.next_document_number(
            _DB(occupied={"X-001", "X-002"}),
            Invoice.invoice_number,
            prefix="X-",
            first=1,
            pad=3,
        )
        == "X-003"
    )
    assert (
        numbering.next_document_number(
            _DB(last="INV-0099"), Invoice.invoice_number, prefix="INV-"
        )
        == "INV-0100"
    )
    assert (
        numbering.next_document_number(
            _DB(last="other"), Invoice.invoice_number, prefix="INV-", first=7, pad=2
        )
        == "INV-07"
    )
    assert (
        numbering.next_document_number(
            _DB(last="INV-0099", occupied={"INV-0100"}),
            Invoice.invoice_number,
            prefix="INV-",
        )
        == "INV-0101"
    )


def test_document_number_wrappers_and_estimate_setting_fallback(
    monkeypatch, db_session
):
    # The invoice counter now reads Settings and the existing numbers, so this
    # runs on a real (empty) database rather than the stub above.
    db = db_session
    assert numbering.next_invoice_number(db) == "1001"
    assert numbering.next_credit_memo_number(db) == "CM-0001"
    assert numbering.next_po_number(db) == "PO-0001"
    monkeypatch.setattr(
        numbering,
        "get_all_settings",
        lambda _db: {"estimate_prefix": "Q-", "estimate_next_number": "bad"},
    )
    assert numbering.next_estimate_number(db) == "Q-1001"
    monkeypatch.setattr(
        numbering,
        "get_all_settings",
        lambda _db: {"estimate_prefix": "", "estimate_next_number": "  "},
    )
    assert numbering.next_estimate_number(db) == "1001"
