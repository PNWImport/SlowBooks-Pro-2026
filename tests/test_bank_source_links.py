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
    "source",
    [
        "bill_payment",
        "journal",
        "manual_journal",
        "manual",
        "expense",
        "deposit",
        "cc_charge",
        "transfer",
        "bank_entry",
        "opening_balance",
    ],
)
def test_posting_links_use_transaction_id_not_source_id(source):
    assert (
        source_link(Transaction(id=91, source_type=source, source_id=23))
        == "/#/journal/91"
    )


def test_unknown_source_has_no_broken_link():
    assert source_link(Transaction(id=91, source_type="unknown")) is None
