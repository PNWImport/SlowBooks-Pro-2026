"""IIF estimate balancing, field sanitation and export date boundaries."""

from datetime import date
from decimal import Decimal

from app.models.accounts import Account, AccountType
from app.models.estimates import Estimate, EstimateLine
from app.models.items import Item, ItemType
from app.services import iif_export as export, iif_import


def test_estimate_balances_tax_and_mapped_fallback_lines(db_session, seed_customer):
    parent = Account(name="Synthetic income", account_type=AccountType.INCOME)
    db_session.add(parent)
    db_session.flush()
    child = Account(name="Child", parent_id=parent.id, account_type=AccountType.INCOME)
    db_session.add(child)
    db_session.flush()
    item = Item(
        name="Synthetic service", item_type=ItemType.SERVICE, income_account_id=child.id
    )
    db_session.add(item)
    db_session.flush()
    estimate = Estimate(
        estimate_number="EST-SYN",
        customer_id=seed_customer.id,
        date=date(2026, 1, 1),
        subtotal=Decimal("20"),
        tax_amount=Decimal("1"),
        total=Decimal("21"),
        notes="Memo\twith\nnewlines",
        lines=[
            EstimateLine(
                item_id=item.id,
                description="Mapped",
                amount=Decimal("10"),
                line_order=0,
            ),
            EstimateLine(description="Fallback", amount=Decimal("10"), line_order=1),
            EstimateLine(description="Zero placeholder", amount=0, line_order=2),
        ],
    )
    db_session.add(estimate)
    db_session.commit()
    text = export.export_estimates(db_session)
    blocks = iif_import.parse_iif(text)["TRNS"]
    assert len(blocks) == 1
    block = blocks[0]
    assert block["trns"]["MEMO"] == "Memo with newlines"
    assert block["trns"]["TRNSTYPE"] == "ESTIMATE"
    assert len(block["spl"]) == 3
    assert {line["ACCNT"] for line in block["spl"]} == {
        "Synthetic income:Child",
        "Service Income",
        "Sales Tax Payable",
    }
    assert sum(Decimal(row["AMOUNT"]) for row in [block["trns"], *block["spl"]]) == 0
    assert export._resolve_account_name(db_session, None) == ""
    assert export._resolve_account_name(db_session, 999999) == ""
    assert export._iif_clean(None) == ""


def test_line_item_fallbacks_cash_tax_and_unallocated_payment(
    db_session, seed_accounts, seed_customer
):
    from app.models.bills import Bill, BillLine
    from app.models.contacts import Vendor
    from app.models.invoices import Invoice, InvoiceLine
    from app.models.payments import Payment
    from app.models.transactions import Transaction

    income = seed_accounts["4000"]
    expense = next(
        account
        for account in seed_accounts.values()
        if account.account_type == AccountType.EXPENSE
    )
    item = Item(
        name="Mapped synthetic",
        item_type=ItemType.SERVICE,
        rate=10,
        income_account_id=income.id,
        expense_account_id=expense.id,
        is_taxable=False,
    )
    vendor = Vendor(name="Synthetic vendor")
    db_session.add_all([item, vendor])
    db_session.flush()
    for receipt in [False, True]:
        db_session.add(
            Invoice(
                invoice_number=f"SYN-{receipt}",
                customer_id=seed_customer.id,
                date=date(2026, 1, 1),
                is_sales_receipt=receipt,
                subtotal=10,
                tax_amount=1,
                total=11,
                lines=[InvoiceLine(item_id=item.id, amount=10), InvoiceLine(amount=0)],
            )
        )
    db_session.add(
        Bill(
            bill_number="SYN-BILL",
            vendor_id=vendor.id,
            date=date(2026, 1, 1),
            subtotal=10,
            total=10,
            lines=[BillLine(item_id=item.id, amount=10), BillLine(amount=0)],
        )
    )
    db_session.add(
        Payment(customer_id=seed_customer.id, date=date(2026, 1, 1), amount=11)
    )
    db_session.add(
        Transaction(
            date=date(2026, 1, 1),
            source_type="deposit",
            description="Empty synthetic deposit",
        )
    )
    db_session.commit()
    exported_item = iif_import.parse_iif(export.export_items(db_session))["INVITEM"][0]
    assert exported_item["ACCNT"] == income.name and exported_item["TAXABLE"] == "N"
    for name in [
        "export_invoices",
        "export_sales_receipts",
        "export_bills",
        "export_payments",
    ]:
        block = iif_import.parse_iif(getattr(export, name)(db_session))["TRNS"][0]
        assert (
            sum(Decimal(row["AMOUNT"]) for row in [block["trns"], *block["spl"]]) == 0
        ), name
        if name == "export_bills":
            assert block["spl"][0]["ACCNT"] == expense.name
        if name == "export_sales_receipts":
            assert any(row["ACCNT"] == "Sales Tax Payable" for row in block["spl"])
    assert not iif_import.parse_iif(export.export_deposits(db_session)).get("TRNS")


def test_export_date_windows_exclude_outside_documents(
    authed_client, db_session, seed_accounts, seed_customer
):
    from tests import test_export_parity as parity

    parity._seed(authed_client, db_session, seed_customer)
    for name in [
        "export_invoices",
        "export_bills",
        "export_deposits",
        "export_sales_receipts",
    ]:
        exporter = getattr(export, name)
        included = iif_import.parse_iif(
            exporter(db_session, date(2026, 7, 1), date(2026, 7, 31))
        )
        assert included["TRNS"], name
        for start, end in [(None, date(2025, 12, 31)), (date(2027, 1, 1), None)]:
            excluded = iif_import.parse_iif(exporter(db_session, start, end))
            assert not excluded.get("TRNS"), name
    assert not iif_import.parse_iif(
        export.export_payments(db_session, date(2027, 1, 1), date(2027, 12, 31))
    ).get("TRNS")
