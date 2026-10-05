"""IIF preflight, row rollback, estimates, and opening-balance edge cases."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models.accounts import Account, AccountType
from app.models.classes import TxnClass
from app.models.contacts import Customer, Vendor
from app.models.estimates import Estimate
from app.models.items import Item, ItemType
from app.models.invoices import Invoice
from app.models.payments import Payment
from app.models.bills import Bill
from app.models.transactions import Transaction
from app.services import iif_import as iif
from app.services.safe_errors import DataProblem


@pytest.mark.parametrize("content", [None, "not an IIF file"])
def test_preflight_rejects_unparseable_or_empty_sections(content):
    result = iif.validate_iif(content)
    assert not result["valid"]
    assert result["errors"]
    assert "AttributeError" not in str(result)


def test_preflight_reports_missing_names_types_and_balance():
    content = (
        "!ACCNT\tNAME\tACCNTTYPE\nACCNT\t\tUNKNOWN\n"
        "!CLASS\tNAME\nCLASS\t\nCLASS\t" + "X" * 101 + "\n"
        "!CUST\tNAME\nCUST\t\n!VEND\tNAME\nVEND\t\n"
        "!INVITEM\tNAME\tINVITEMTYPE\nINVITEM\t\tUNKNOWN\n"
        "!TRNS\tTRNSTYPE\tDATE\tAMOUNT\nTRNS\t\nENDTRNS\n"
        "TRNS\tINVOICE\t\t10\nENDTRNS\n"
    )
    result = iif.validate_iif(content)
    assert not result["valid"]
    assert set(result["sections_found"]) == {
        "ACCNT",
        "CLASS",
        "CUST",
        "VEND",
        "INVITEM",
        "TRNS",
    }
    assert len(result["errors"]) == 7
    assert len(result["warnings"]) == 4
    assert any("unbalanced" in message for message in result["warnings"])


def test_preflight_accepts_balanced_document():
    content = "!TRNS\tTRNSTYPE\tDATE\tAMOUNT\n!SPL\tAMOUNT\nTRNS\tINVOICE\t01/01/2026\t10\nSPL\t-10\nENDTRNS\n"
    result = iif.validate_iif(content)
    assert result["valid"] and not result["warnings"] and not result["errors"]
    assert iif._parse_iif_date("not a date") is None


@pytest.mark.parametrize(
    "kind,model",
    [
        ("accounts", Account),
        ("classes", TxnClass),
        ("customers", Customer),
        ("vendors", Vendor),
        ("items", Item),
    ],
)
@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_one_failed_row_does_not_poison_later_rows(db_session, kind, model, error_type):
    def reject(session, flush_context, instances):
        if any(
            isinstance(row, model) and row.name == "Rejected" for row in session.new
        ):
            raise error_type("synthetic row failure")

    event.listen(db_session, "before_flush", reject)
    try:
        result = getattr(iif, f"import_{kind}")(
            db_session,
            [
                {},
                {"NAME": "Rejected"},
                {"NAME": "Good", "ADDR4": "Test, WA 00000"},
                {"NAME": "Good"},
            ],
        )
    finally:
        event.remove(db_session, "before_flush", reject)
    db_session.commit()
    assert result["imported"] == 1
    assert len(result["errors"]) == 2
    assert "synthetic row failure" not in str(result["errors"])
    assert any(
        error["message"] == "unexpected error — the server log has the details"
        for error in result["errors"]
    )
    assert db_session.query(model).one().name == "Good"


def test_estimate_item_tax_rounding_and_deduplication(db_session):
    item = Item(name="Service", item_type=ItemType.SERVICE)
    db_session.add(item)
    db_session.commit()
    block = {
        "trns": {
            "TRNSTYPE": "ESTIMATE",
            "DOCNUM": "EST-1",
            "NAME": "Synthetic",
            "DATE": "2026-01-01",
        },
        "spl": [
            {
                "ACCNT": "Income",
                "AMOUNT": "-10.005",
                "INVITEM": "Service",
                "QNTY": "2",
                "MEMO": "Work",
            },
            {"ACCNT": "Sales Tax", "AMOUNT": "-1"},
        ],
    }
    result = iif.import_transactions(db_session, [block])
    db_session.commit()
    assert result["errors"] == [] and result["imported"]["estimates"] == 1
    estimate = db_session.query(Estimate).one()
    assert estimate.date == date(2026, 1, 1)
    assert estimate.subtotal == Decimal("10.01")
    assert estimate.total == Decimal("11.01") and estimate.tax_amount == 1
    assert estimate.lines[0].item_id == item.id
    assert estimate.lines[0].rate == Decimal("5.01")
    assert iif.import_transactions(db_session, [block])["imported"]["estimates"] == 0
    # A blank customer NAME is said, not dropped.
    with pytest.raises(DataProblem, match="missing customer NAME"):
        iif._import_estimate(db_session, {"NAME": " "}, [])


@pytest.mark.parametrize("amount", [Decimal("10"), Decimal("-10")])
def test_opening_balance_uses_equity_plug(db_session, amount):
    asset = Account(name="Bank", account_type=AccountType.ASSET)
    equity = Account(name="Retained Earnings", account_type=AccountType.EQUITY)
    db_session.add_all([asset, equity])
    db_session.commit()
    result = iif._create_opening_balance_entry(db_session, [(asset.id, amount)])
    assert result["created"]
    db_session.flush()
    transaction = db_session.get(Transaction, result["transaction_id"])
    assert (
        sum(line.debit for line in transaction.lines)
        == sum(line.credit for line in transaction.lines)
        == abs(amount)
    )
    assert asset.balance == equity.balance == amount


def test_missing_equity_and_bad_account_report_opening_failure(db_session):
    asset = Account(name="Bank", account_type=AccountType.ASSET)
    db_session.add(asset)
    db_session.commit()
    result = iif._create_opening_balance_entry(db_session, [(asset.id, Decimal("10"))])
    assert not result["created"] and "Could not find" in result["warning"]
    result = iif._create_opening_balance_entry(
        db_session, [(999999, Decimal("10")), (asset.id, Decimal("-10"))]
    )
    assert not result["created"] and "journal entry failed" in result["warning"]


def test_account_import_surfaces_missing_equity_warning(db_session):
    result = iif.import_accounts(
        db_session, [{"NAME": "Bank", "ACCNTTYPE": "BANK", "OBAMOUNT": "10"}]
    )
    assert result["imported"] == 1
    assert result["warnings"] and not result["opening_balance"]["created"]


@pytest.mark.parametrize("kind", ["INVOICE", "CASH SALE"])
def test_unpostable_documents_warn_without_fabricating_journal(db_session, kind):
    block = {
        "trns": {
            "TRNSTYPE": kind,
            "DOCNUM": "UNPOSTED",
            "NAME": "Synthetic",
            "AMOUNT": "10",
        },
        "spl": [{"ACCNT": "Unmapped", "AMOUNT": "-10"}],
    }
    result = iif.import_transactions(db_session, [block])
    assert not result["errors"]
    assert any(
        "journal entry could not be created" in warning
        for warning in result["warnings"]
    )
    assert db_session.query(Transaction).count() == 0
    if kind == "CASH SALE":
        # Direct helper dedup must not create a second payment for a receipt.
        assert iif._import_cash_sale(db_session, block["trns"], block["spl"]) is None


def test_invoice_tax_item_zero_line_and_default_income(db_session, seed_accounts):
    item = Item(name="Synthetic item", item_type=ItemType.SERVICE)
    db_session.add(item)
    db_session.commit()
    result = iif.import_transactions(
        db_session,
        [
            {
                "trns": {
                    "TRNSTYPE": "INVOICE",
                    "DOCNUM": "FALLBACK",
                    "NAME": "Synthetic",
                    "AMOUNT": "11",
                },
                "spl": [
                    {
                        "ACCNT": "Unmapped income",
                        "INVITEM": item.name,
                        "QNTY": "2",
                        "AMOUNT": "-10",
                    },
                    {"ACCNT": "Sales Tax Payable", "AMOUNT": "-1"},
                    {"ACCNT": "Unmapped zero", "AMOUNT": "0"},
                ],
            }
        ],
    )
    db_session.commit()
    assert not result["errors"]
    invoice = db_session.query(Invoice).one()
    assert invoice.total == 11 and invoice.tax_amount == 1
    assert invoice.lines[0].item_id == item.id and invoice.lines[0].rate == 5
    assert invoice.transaction_id
    transaction = db_session.get(Transaction, invoice.transaction_id)
    assert (
        sum(line.debit for line in transaction.lines)
        == sum(line.credit for line in transaction.lines)
        == 11
    )
    assert any(
        "unmatched: Unmapped income" in line.description for line in transaction.lines
    )
    with pytest.raises(DataProblem, match="missing customer NAME"):
        iif._import_invoice(db_session, {"NAME": ""}, [])


@pytest.mark.parametrize(
    "field,value", [("NAME", ""), ("ACCNT", ""), ("ACCNT", "Unknown"), ("DOCNUM", "")]
)
def test_bill_required_header_validation(db_session, seed_accounts, field, value):
    db_session.add(Vendor(name="Synthetic vendor"))
    db_session.commit()
    trns = {
        "NAME": "Synthetic vendor",
        "ACCNT": "Accounts Payable",
        "DOCNUM": "B-1",
        "AMOUNT": "-10",
    }
    trns[field] = value
    with pytest.raises(ValueError):
        iif._import_bill(db_session, trns, [{"ACCNT": "Supplies", "AMOUNT": "10"}])
    assert db_session.query(Bill).count() == 0


@pytest.mark.parametrize("kind", ["BILL", "DEPOSIT"])
@pytest.mark.parametrize("split_account", ["", "Unmapped source"])
def test_invalid_split_account_rejected_before_write(
    db_session, seed_accounts, kind, split_account
):
    db_session.add(Vendor(name="Synthetic vendor"))
    db_session.commit()
    amount = -10 if kind == "BILL" else 10
    trns = {
        "NAME": "Synthetic vendor",
        "ACCNT": "Accounts Payable" if kind == "BILL" else "Checking",
        "DOCNUM": "INVALID-SPLIT",
        "AMOUNT": str(amount),
    }
    with pytest.raises(ValueError):
        getattr(iif, f"_import_{kind.lower()}")(
            db_session, trns, [{"ACCNT": split_account, "AMOUNT": str(-amount)}]
        )
    assert db_session.query(Transaction).count() == 0


def test_deposit_missing_bank_and_multiple_classes(db_session):
    with pytest.raises(ValueError, match="missing bank"):
        iif._import_deposit(db_session, {"AMOUNT": "10"}, [{"AMOUNT": "-10"}])
    with pytest.raises(ValueError, match="multiple CLASS"):
        iif._resolve_block_class(
            db_session, "BILL", "CLASS-1", [{"CLASS": "A"}, {"CLASS": "B"}]
        )


def test_unmapped_numberless_cash_sale_is_deduplicated(db_session):
    trns = {"NAME": "Synthetic", "AMOUNT": "10", "ACCNT": "Unknown"}
    splits = [{"ACCNT": "Unmapped income", "AMOUNT": "-10"}]
    receipt = iif._import_cash_sale(db_session, trns, splits)
    db_session.commit()
    assert receipt.invoice_number
    assert iif._import_cash_sale(db_session, trns, splits) is None


def test_cash_sale_unknown_deposit_uses_undeposited_funds(db_session, seed_accounts):
    receipt = iif._import_cash_sale(
        db_session,
        {
            "NAME": "Synthetic",
            "DOCNUM": "CASH-FALLBACK",
            "AMOUNT": "10",
            "ACCNT": "Unknown",
        },
        [{"ACCNT": "Sales", "AMOUNT": "-10"}],
    )
    db_session.commit()
    payment = db_session.query(Payment).one()
    deposit = db_session.get(Account, payment.deposit_to_account_id)
    assert deposit.account_number == "1200"
    assert payment.amount == receipt.amount_paid == Decimal("10")
    assert receipt.balance_due == 0
    for transaction in db_session.query(Transaction).all():
        assert sum(line.debit for line in transaction.lines) == sum(
            line.credit for line in transaction.lines
        )
