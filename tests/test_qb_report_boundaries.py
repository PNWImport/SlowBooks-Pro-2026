"""QB report malformed-row handling, receipt rollback and numbering collisions."""

import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from app.models.invoices import Invoice
from app.services import qb_report_import as report


@pytest.mark.parametrize(
    "value,amount",
    [(None, "0"), ("bad", "0"), ("$1,234.56", "1234.56"), ("-2.01", "-2.01")],
)
def test_report_amount_forms(value, amount):
    assert report._amount(value) == Decimal(amount)


def test_optional_cells_bad_dates_and_tax_rates():
    assert report._cell([], {"Name": 2}, "Name") == ""
    assert report._cell([], {}, "Missing") == ""
    assert report._parse_date("invalid") is None
    assert report._parse_date("2026-01-02") == date(2026, 1, 2)
    assert report._parse_tax_rate("bad%") == report._parse_tax_rate("6.4") == 0
    assert report._parse_tax_rate("6.4%") == Decimal("0.064")


def test_number_collisions_do_not_reuse_existing_invoice(db_session, seed_customer):
    for number in ["1", "SR-1", "SR-1-1"]:
        db_session.add(
            Invoice(
                invoice_number=number,
                customer_id=seed_customer.id,
                date=date(2026, 1, 1),
            )
        )
    db_session.commit()
    assert report._assign_number(db_session, "1") == "SR-1-2"
    assert report._assign_number(db_session, "") not in {"1", "SR-1", "SR-1-1"}


def test_invalid_receipt_does_not_block_later_balanced_receipt(
    db_session, seed_accounts
):
    columns = [*report.REQUIRED_COLUMNS, "Num", "Memo"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerow({"Date": "01/01/2026", "Account": "Service Income", "Credit": "1"})
    for number, detail in [("BAD", "9"), ("GOOD", "10")]:
        writer.writerow(
            {
                "Date": "01/01/2026",
                "Name": "Synthetic",
                "Account": "Checking",
                "Split": "-SPLIT-",
                "Debit": "10",
                "Num": number,
            }
        )
        writer.writerow(
            {
                "Date": "01/01/2026",
                "Account": "Service Income",
                "Credit": detail,
                "Memo": "Synthetic sale",
            }
        )
    result = report.import_sales_receipt_report(db_session, buffer.getvalue())
    assert result["imported"] == 1 and len(result["errors"]) == 2
    assert any("before any receipt" in error for error in result["errors"])
    assert any("do not equal" in error for error in result["errors"])
    receipt = db_session.query(Invoice).one()
    assert receipt.invoice_number == "GOOD" and receipt.total == Decimal("10")
    assert receipt.transaction_id


@pytest.mark.parametrize("kind", ["deposit", "check"])
def test_wrong_report_header_is_rejected(db_session, kind):
    result = getattr(report, f"import_{kind}_report")(db_session, "not,a,report\n")
    assert result["errors"] and result[kind + "s"] == 0


@pytest.mark.parametrize("chart", ["full", "ar-only", "empty"])
def test_receipt_item_and_unmapped_account_fallbacks(db_session, request, chart):
    from app.models.accounts import Account, AccountType
    from app.models.items import Item, ItemType
    from app.models.payments import Payment

    if chart == "full":
        request.getfixturevalue("seed_accounts")
    elif chart == "ar-only":
        db_session.add(
            Account(
                name="Accounts Receivable",
                account_number="1100",
                account_type=AccountType.ASSET,
            )
        )
    item = Item(name="Synthetic item", item_type=ItemType.SERVICE)
    db_session.add(item)
    db_session.commit()
    columns = [*report.REQUIRED_COLUMNS, "Item"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerow(
        {
            "Date": "01/01/2026",
            "Name": "Synthetic",
            "Account": "Unmapped bank",
            "Split": "-SPLIT-",
            "Debit": "10",
        }
    )
    writer.writerow(
        {
            "Date": "01/01/2026",
            "Account": "Unmapped income",
            "Credit": "10",
            "Item": item.name,
        }
    )
    writer.writerow({"Date": "01/01/2026", "Account": "Unmapped zero", "Credit": "0"})
    result = report.import_sales_receipt_report(db_session, buffer.getvalue())
    assert result["imported"] == 1 and not result["errors"], result
    receipt = db_session.query(Invoice).one()
    assert receipt.lines[0].item_id == item.id
    payment = db_session.query(Payment).one()
    if chart == "full":
        assert receipt.transaction_id and payment.transaction_id
        assert payment.deposit_to_account.account_number == "1200"
        assert any("default income" in warning for warning in result["warnings"])
    else:
        assert receipt.transaction_id is None and payment.transaction_id is None
        assert any(
            "journal entry could not be created" in warning
            for warning in result["warnings"]
        )
        assert any("payment journal entry" in warning for warning in result["warnings"])
        if chart == "empty":
            assert any(
                "invoice journal entry" in warning for warning in result["warnings"]
            )


def test_sales_receipt_hook_failure_rolls_back_whole_receipt(
    db_session, seed_accounts, monkeypatch
):
    from app.models.payments import Payment
    from app.services import inventory_hooks
    from tests import test_qb_report_import as fixture

    def fail(*args, **kwargs):
        raise ValueError("Synthetic inventory rejection")

    monkeypatch.setattr(inventory_hooks, "post_sale_for_invoice", fail)
    result = report.import_sales_receipt_report(db_session, fixture.FIXTURE.read_text())
    assert result["imported"] == 0 and len(result["errors"]) == 3
    assert "Synthetic inventory rejection" not in str(result["errors"])
    assert all("server log" in message for message in result["errors"])
    assert db_session.query(Invoice).count() == db_session.query(Payment).count() == 0


def test_check_original_amount_fallback_and_zero_split(db_session, seed_accounts):
    from app.models.accounts import AccountType
    from app.models.transactions import Transaction

    expense = next(
        account.name
        for account in seed_accounts.values()
        if account.account_type == AccountType.EXPENSE
    )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=report.CHECK_COLUMNS)
    writer.writeheader()
    writer.writerow(
        {
            "Type": "Check",
            "Date": "01/01/2026",
            "Name": "Synthetic",
            "Account": "Checking",
            "Original Amount": "-10",
        }
    )
    writer.writerow({"Account": expense, "Original Amount": "10"})
    writer.writerow({"Account": expense, "Original Amount": "0"})
    result = report.import_check_report(db_session, output.getvalue())
    assert result["checks"] == 1 and not result["errors"]
    assert len(db_session.query(Transaction).one().lines) == 2


def test_deposit_report_warns_about_other_transaction_types(db_session):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=report.DEPOSIT_COLUMNS)
    writer.writeheader()
    writer.writerow(
        {
            "Type": "Transfer",
            "Date": "01/01/2026",
            "Name": "Synthetic",
            "Account": "Checking",
            "Amount": "10",
        }
    )
    result = report.import_deposit_report(db_session, output.getvalue())
    assert result["deposits"] == 0 and not result["errors"]
    assert len(result["warnings"]) == 1 and "Transfer" in result["warnings"][0]


def test_unknown_report_dispatch_is_explicit(db_session):
    result = report.import_qb_report(db_session, "unknown,columns\n")
    assert result["detected"] is None and result["errors"]
    assert result["sales_receipts"] == result["checks"] == result["deposits"] == 0


@pytest.mark.parametrize("kind", ["deposit", "check"])
@pytest.mark.parametrize("fault", ["date", "bank", "zero", "split-account", "balance"])
def test_invalid_block_rolls_back_and_later_block_succeeds(
    db_session, seed_accounts, kind, fault
):
    from app.models.transactions import Transaction
    from app.models.accounts import AccountType

    expense_name = next(
        account.name
        for account in seed_accounts.values()
        if account.account_type == AccountType.EXPENSE
    )
    columns = list(
        report.DEPOSIT_COLUMNS if kind == "deposit" else report.CHECK_COLUMNS
    )
    columns += ["Num", "Memo"]
    total_key = "Amount" if kind == "deposit" else "Original Amount"
    split_key = "Amount" if kind == "deposit" else "Paid Amount"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for bad in [True, False]:
        header = {
            "Type": kind.title(),
            "Date": "01/01/2026",
            "Name": "Synthetic",
            "Account": "Checking",
            total_key: "10" if kind == "deposit" else "-10",
            "Num": "BAD" if bad else "GOOD",
            "Memo": "Synthetic memo",
        }
        detail = {
            "Account": "Service Income" if kind == "deposit" else expense_name,
            split_key: "-10",
        }
        if bad:
            if fault == "date":
                header["Date"] = "bad date"
            elif fault == "bank":
                header["Account"] = "Unknown synthetic account"
            elif fault == "zero":
                header[total_key] = "0"
            elif fault == "split-account":
                detail["Account"] = "Unknown synthetic account"
            else:
                detail[split_key] = "-9"
        writer.writerow(header)
        writer.writerow(detail)
    result = getattr(report, f"import_{kind}_report")(db_session, buffer.getvalue())
    assert result[kind + "s"] == 1 and len(result["errors"]) == 1, result
    transaction = db_session.query(Transaction).one()
    assert (
        sum(line.debit for line in transaction.lines)
        == sum(line.credit for line in transaction.lines)
        == Decimal("10")
    )
