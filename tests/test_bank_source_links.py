"""Ledger links must use a reachable document or posting view, with the right ID."""

import pytest

from app.models.transactions import Transaction
from app.services.bank_register import source_link


@pytest.mark.parametrize("source", ["invoice", "bill", "payment"])
def test_document_links_use_document_id(source):
    txn = Transaction(id=91, source_type=source, source_id=23)
    assert source_link(txn) == f"/#/{source}s/23"
    txn.source_id = None
    assert source_link(txn) is None


@pytest.mark.parametrize(
    "source,expected",
    [
        ("bill_payment", "/#/bill-payments/23"),
        ("vendor_credit", "/#/vendor-credits/23"),
        ("journal", "/#/journal/23"),
        ("manual_journal", "/#/journal/23"),
    ],
)
def test_document_backed_postings_link_by_source_id(source, expected):
    assert source_link(Transaction(id=91, source_type=source, source_id=23)) == expected
    assert source_link(Transaction(id=91, source_type=source)) is None


@pytest.mark.parametrize(
    "source,expected",
    [
        ("manual", "/#/journal/91"),
        ("expense", "/#/expenses/91"),
        ("deposit", "/#/deposits/91"),
        ("cc_charge", "/#/cc-charges/91"),
        ("transfer", "/#/banking/transfers/91"),
        ("bank_entry", "/#/journal/91"),
        ("opening_balance", "/#/journal/91"),
        ("qbo_ledger", "/#/journal/91"),
        ("qbo_journal", "/#/journal/91"),
    ],
)
def test_posting_links_use_transaction_id_not_source_id(source, expected):
    assert (
        source_link(Transaction(id=91, source_type=source, source_id=23)) == expected
    )


def test_unknown_source_has_no_broken_link():
    assert source_link(Transaction(id=91, source_type="unknown")) is None
