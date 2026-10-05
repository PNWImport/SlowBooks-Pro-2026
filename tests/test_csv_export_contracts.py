"""CSV exports preserve values and neutralize formula-like customer data."""

import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from app.models.accounts import Account, AccountType
from app.models.contacts import Customer, Vendor
from app.models.items import Item, ItemType
from app.models.invoices import Invoice, InvoiceStatus
from app.services import csv_export as export


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
@pytest.mark.parametrize(
    "kind,model", [("customers", Customer), ("vendors", Vendor), ("items", Item)]
)
def test_active_entities_escape_text_preserve_money(db_session, prefix, kind, model):
    name = prefix + 'Synthetic,"name"'
    args = {"name": name, "is_active": True}
    if kind == "items":
        args.update(
            item_type=ItemType.SERVICE,
            rate=Decimal("12.34"),
            cost=Decimal("2.01"),
            is_taxable=False,
            description="@Synthetic description",
        )
    else:
        args.update(
            balance=Decimal("12.34"), company="=Synthetic company", terms="Net 30"
        )
    inactive = {"name": "Inactive synthetic", "is_active": False}
    if kind == "items":
        inactive["item_type"] = ItemType.SERVICE
    db_session.add_all([model(**args), model(**inactive)])
    db_session.commit()
    result = rows(getattr(export, "export_" + kind)(db_session))
    assert len(result) == 1 and result[0]["Name"] == "'" + name
    if kind == "items":
        assert result[0]["Rate"] == "12.34" and result[0]["Cost"] == "2.01"
        assert result[0]["Description"] == "'@Synthetic description"
        assert result[0]["Taxable"] == "False"
    else:
        assert result[0]["Balance"] == "12.34"
        assert result[0]["Company"] == "'=Synthetic company"
        assert result[0]["Email"] == ""


def test_invoice_date_bounds_and_order(db_session, seed_customer):
    for idx, day in enumerate([3, 1, 2]):
        db_session.add(
            Invoice(
                invoice_number=f"=SYN-{idx}",
                customer_id=seed_customer.id,
                date=date(2026, 1, day),
                due_date=None,
                status=InvoiceStatus.PARTIAL,
                subtotal=Decimal("10"),
                tax_amount=Decimal("0.30"),
                total=Decimal("10.30"),
                amount_paid=Decimal("0.30"),
                balance_due=Decimal("10"),
            )
        )
    db_session.commit()
    result = rows(
        export.export_invoices(db_session, date(2026, 1, 2), date(2026, 1, 3))
    )
    assert [row["Date"] for row in result] == ["2026-01-02", "2026-01-03"]
    assert all(row["Invoice #"].startswith("'=SYN-") for row in result)
    assert all(row["Due Date"] == "" and row["Total"] == "10.3" for row in result)
    assert len(rows(export.export_invoices(db_session))) == 3


def test_accounts_preserve_negative_numeric_balance(db_session):
    db_session.add_all(
        [
            Account(
                name="=Synthetic",
                account_number="1000",
                account_type=AccountType.ASSET,
                balance=Decimal("-12.34"),
                is_active=False,
            ),
            Account(name="No number", account_type=AccountType.EXPENSE, balance=0),
        ]
    )
    db_session.commit()
    result = rows(export.export_accounts(db_session))
    assert len(result) == 2
    account = next(row for row in result if row["Number"] == "1000")
    assert account["Name"] == "'=Synthetic"
    assert account["Balance"] == "-12.34" and account["Active"] == "False"


def test_interchange_exports_honor_both_date_bounds(
    authed_client, db_session, seed_accounts, seed_customer
):
    from tests import test_export_parity as parity

    parity._seed(authed_client, db_session, seed_customer)
    for name in ["export_bills", "export_deposits", "export_sales_receipts"]:
        exporter = getattr(export, name)
        selected = rows(exporter(db_session, date(2026, 7, 1), date(2026, 7, 31)))
        assert selected, name
        assert all("2026-07-01" <= row["Date"] <= "2026-07-31" for row in selected)
        assert rows(exporter(db_session, date_to=date(2025, 12, 31))) == []
        assert rows(exporter(db_session, date_from=date(2027, 1, 1))) == []


def test_missing_dimensions_are_empty(db_session):
    assert (
        export._cls_name(db_session, None) == export._cls_name(db_session, 999999) == ""
    )
    assert (
        export._job_name(db_session, None) == export._job_name(db_session, 999999) == ""
    )
