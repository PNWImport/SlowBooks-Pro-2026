"""Local QBO export contracts: real ORM/SDK objects, only remote saves stubbed."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from importlib import import_module

import pytest

from app.models.accounts import Account, AccountType
from app.models.contacts import Customer, Vendor
from app.models.invoices import Invoice, InvoiceLine
from app.models.items import Item, ItemType
from app.models.payments import Payment, PaymentAllocation
from app.models.qbo_mapping import QBOMapping
from app.services import qbo_export


@pytest.fixture
def remote(monkeypatch):
    calls = []
    fail = set()
    client = object()
    monkeypatch.setattr(qbo_export, "get_qbo_client", lambda db: client)

    def save(obj, qb):
        assert qb is client
        entity = type(obj).__name__.lower()
        if entity in fail:
            raise RuntimeError("synthetic remote rejection")
        obj.Id = f"remote-{entity}-{len(calls) + 1}"
        obj.SyncToken = "0"
        calls.append((entity, deepcopy(obj)))
        return obj

    for entity in ("account", "customer", "vendor", "item", "invoice", "payment"):
        cls = getattr(import_module(f"quickbooks.objects.{entity}"), entity.title())
        monkeypatch.setattr(cls, "save", save)
    return calls, fail


@pytest.fixture
def export_rows(db_session):
    income = Account(
        name="Income",
        account_type=AccountType.INCOME,
        account_number="4000",
        description="Synthetic income",
    )
    expense = Account(name="Expense", account_type=AccountType.EXPENSE)
    bank = Account(name="Bank", account_type=AccountType.ASSET)
    customer = Customer(
        name="Customer",
        company="Example",
        email="test@example.invalid",
        phone="555",
        mobile="556",
        fax="557",
        notes="Memo",
        bill_address1="1 Test",
        bill_city="Test",
        bill_state="WA",
        bill_zip="00000",
        ship_address1="2 Test",
        ship_city="Other",
    )
    vendor = Vendor(
        name="Vendor",
        company="Supplier",
        email="vendor@example.invalid",
        phone="555",
        fax="557",
        notes="Vendor memo",
        account_number="ACCT",
        address1="3 Test",
        city="Test",
        state="WA",
        zip="00000",
    )
    db_session.add_all([income, expense, bank, customer, vendor])
    db_session.flush()
    expense.parent_id = income.id
    item = Item(
        name="Service",
        item_type=ItemType.SERVICE,
        description="Work",
        rate=Decimal("12.34"),
        cost=Decimal("5.67"),
        income_account_id=income.id,
        expense_account_id=expense.id,
    )
    db_session.add(item)
    db_session.flush()
    invoice = Invoice(
        invoice_number="EXPORT-1",
        customer_id=customer.id,
        date=date(2026, 1, 1),
        due_date=date(2026, 1, 31),
        notes="Invoice memo",
        total=Decimal("24.68"),
        balance_due=Decimal("24.68"),
    )
    payment = Payment(
        customer_id=customer.id,
        date=date(2026, 1, 2),
        amount=Decimal("24.68"),
        reference="CHECK-1",
        deposit_to_account_id=bank.id,
    )
    db_session.add_all([invoice, payment])
    db_session.flush()
    db_session.add_all(
        [
            InvoiceLine(
                invoice_id=invoice.id,
                item_id=item.id,
                description="Work",
                quantity=2,
                rate=Decimal("12.34"),
                amount=Decimal("24.68"),
                line_order=0,
            ),
            PaymentAllocation(
                payment_id=payment.id, invoice_id=invoice.id, amount=Decimal("24.68")
            ),
        ]
    )
    db_session.commit()
    return income, expense, bank, customer, vendor, item, invoice, payment


def test_export_all_preserves_dependency_references(db_session, export_rows, remote):
    result = qbo_export.export_all(db_session)
    assert result == {
        "accounts": 3,
        "customers": 1,
        "vendors": 1,
        "items": 1,
        "invoices": 1,
        "payments": 1,
        "errors": [],
    }
    calls, _ = remote
    assert [kind for kind, _ in calls] == ["account"] * 3 + [
        "customer",
        "vendor",
        "item",
        "invoice",
        "payment",
    ]
    by_kind = {kind: obj for kind, obj in calls}
    accounts = {obj.Name: obj for kind, obj in calls if kind == "account"}
    assert accounts["Expense"].ParentRef == {"value": accounts["Income"].Id}
    assert accounts["Expense"].SubAccount is True
    assert accounts["Income"].AcctNum == "4000"
    assert accounts["Income"].Description == "Synthetic income"
    customer = by_kind["customer"]
    assert customer.BillAddr["Line1"] == "1 Test"
    assert customer.ShipAddr["Line1"] == "2 Test"
    assert customer.PrimaryEmailAddr == {"Address": "test@example.invalid"}
    assert customer.Mobile == {"FreeFormNumber": "556"}
    assert customer.Notes == "Memo"
    assert by_kind["vendor"].AcctNum == "ACCT"
    item = by_kind["item"]
    assert item.IncomeAccountRef == {"value": accounts["Income"].Id}
    assert item.ExpenseAccountRef == {"value": accounts["Expense"].Id}
    assert (item.UnitPrice, item.PurchaseCost) == (12.34, 5.67)
    invoice = by_kind["invoice"]
    assert invoice.CustomerRef == {"value": customer.Id}
    assert invoice.DocNumber == "EXPORT-1"
    assert invoice.TxnDate == "2026-01-01"
    assert invoice.DueDate == "2026-01-31"
    assert invoice.Line == [
        {
            "DetailType": "SalesItemLineDetail",
            "Amount": 24.68,
            "Description": "Work",
            "SalesItemLineDetail": {
                "Qty": 2.0,
                "UnitPrice": 12.34,
                "ItemRef": {"value": item.Id},
            },
        }
    ]
    payment = by_kind["payment"]
    assert payment.TotalAmt == 24.68
    assert payment.DepositToAccountRef == {"value": accounts["Bank"].Id}
    assert payment.Line == [
        {"Amount": 24.68, "LinkedTxn": [{"TxnId": invoice.Id, "TxnType": "Invoice"}]}
    ]
    assert db_session.query(QBOMapping).count() == 8
    assert all(row.qbo_sync_token == "0" for row in db_session.query(QBOMapping))
    # Repeat exports must not create another remote copy.
    assert qbo_export.export_all(db_session) == dict.fromkeys(
        result.keys() - {"errors"}, 0
    ) | {"errors": []}
    assert len(calls) == 8


@pytest.mark.parametrize(
    "entity", ["account", "customer", "vendor", "item", "invoice", "payment"]
)
def test_remote_rejection_is_reported_without_mapping(
    db_session, export_rows, remote, entity
):
    calls, fail = remote
    # Pre-map dependencies so the requested entity reaches the remote boundary.
    for kind, row in zip(
        ["account"] * 3 + ["customer", "vendor", "item", "invoice", "payment"],
        export_rows,
    ):
        if kind != entity:
            db_session.add(
                QBOMapping(
                    entity_type=kind,
                    slowbooks_id=row.id,
                    qbo_id=f"prior-{kind}-{row.id}",
                )
            )
    db_session.commit()
    fail.add(entity)
    result = getattr(qbo_export, f"export_{entity}s")(db_session)
    assert result["exported"] == 0
    assert result["errors"]
    assert all(
        error["message"] == "unexpected error — the server log has the details"
        for error in result["errors"]
    )
    assert not db_session.query(QBOMapping).filter_by(entity_type=entity).count()
    assert calls == []


def test_item_uses_mapped_default_income(db_session, export_rows, remote):
    income, _, _, _, _, item, _, _ = export_rows
    item.income_account_id = None
    db_session.add(
        QBOMapping(
            entity_type="account", slowbooks_id=income.id, qbo_id="default-income"
        )
    )
    db_session.commit()
    assert qbo_export.export_items(db_session) == {"exported": 1, "errors": []}
    assert remote[0][0][1].IncomeAccountRef == {"value": "default-income"}


@pytest.mark.parametrize("entity", ["invoice", "payment"])
def test_missing_customer_mapping_never_saves_remote(
    db_session, export_rows, remote, entity
):
    result = getattr(qbo_export, f"export_{entity}s")(db_session)
    assert result["exported"] == 0
    assert "not mapped to QBO" in result["errors"][0]["message"]
    assert remote[0] == []
