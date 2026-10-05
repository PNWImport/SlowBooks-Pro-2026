"""Exercise QBO conversion with synthetic SDK responses and a real database."""

from datetime import date
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace as Obj

import pytest

from app.models.accounts import Account
from app.models.contacts import Customer, Vendor
from app.models.invoices import Invoice, InvoiceStatus
from app.models.items import Item
from app.models.payments import Payment, PaymentAllocation
from app.models.qbo_mapping import QBOMapping
from app.services import qbo_import

ENTITIES = [
    "accounts",
    "customers",
    "vendors",
    "items",
    "invoices",
    "payments",
    "sales_receipts",
]


@pytest.fixture
def remote_import(monkeypatch):
    records = {kind: [] for kind in ENTITIES}
    failures = set()
    class Client:
        """import_all also reads the (empty) General Ledger report."""

        def get_report(self, name, qs):
            return {
                "Header": {
                    "StartPeriod": qs["start_date"],
                    "EndPeriod": qs["end_date"],
                    "ReportBasis": "Accrual",
                },
                "Columns": {
                    "Column": [
                        {"ColTitle": t}
                        for t in (
                            "Date",
                            "Transaction Type",
                            "Num",
                            "Name",
                            "Memo/Description",
                            "Split",
                            "Amount",
                            "Balance",
                        )
                    ]
                },
                "Rows": {"Row": []},
            }

    client = Client()
    monkeypatch.setattr(qbo_import, "get_qbo_client", lambda db: client)
    for kind in ENTITIES:
        module, classname = (
            ("salesreceipt", "SalesReceipt")
            if kind == "sales_receipts"
            else (kind[:-1], kind[:-1].title())
        )
        cls = getattr(import_module(f"quickbooks.objects.{module}"), classname)

        def all_records(
            qb, start_position=1, max_results=100, kind=kind, **_unused
        ):
            assert qb is client
            if kind in failures:
                raise RuntimeError("synthetic query failure")
            return list(records[kind])[start_position - 1 :][:max_results]

        monkeypatch.setattr(cls, "all", all_records)
        if kind == "accounts":
            # inactive accounts are fetched with an explicit query
            monkeypatch.setattr(
                cls, "query", classmethod(lambda c, select, *, qb: [])
            )
    from quickbooks.objects.journalentry import JournalEntry

    from app.services import qbo_ledger_import

    monkeypatch.setattr(
        JournalEntry,
        "all",
        classmethod(lambda c, qb, start_position=1, max_results=100: []),
    )

    monkeypatch.setattr(qbo_ledger_import, "get_qbo_client", lambda db: client)
    return records, failures


def populate_remote(records):
    records["accounts"] = [
        Obj(
            Id="expense",
            Name="Expense",
            AccountType="Expense",
            FullyQualifiedName="Income:Expense",
            ParentRef=Obj(value="income"),
        ),
        Obj(
            Id="income",
            Name="Income",
            AccountType="Income",
            FullyQualifiedName="Income",
            AcctNum="4000",
            CurrentBalance="24.68",
        ),
    ]
    address = Obj(
        Line1="1 Test",
        Line2="Suite 2",
        City="Test",
        CountrySubDivisionCode="WA",
        PostalCode="00000",
    )
    records["customers"] = [
        Obj(
            Id="customer",
            DisplayName="Customer",
            CompanyName="Example",
            BillAddr=address,
            ShipAddr=address,
            PrimaryEmailAddr=Obj(Address="test@example.invalid"),
            PrimaryPhone=Obj(FreeFormNumber="555"),
            Mobile=Obj(FreeFormNumber="556"),
            Fax=Obj(FreeFormNumber="557"),
            SalesTermRef=Obj(name="Net 15"),
            Notes="Memo",
            WebAddr={"URI": "https://example.invalid"},
        )
    ]
    records["vendors"] = [
        Obj(
            Id="vendor",
            DisplayName="Vendor",
            BillAddr=address,
            PrimaryEmailAddr=Obj(Address="vendor@example.invalid"),
            PrimaryPhone=Obj(FreeFormNumber="555"),
            Fax=Obj(FreeFormNumber="557"),
            TermRef=Obj(name="Net 15"),
            AcctNum="VENDOR",
        )
    ]
    records["items"] = [
        Obj(
            Id="item",
            Name="Item",
            Type="Service",
            UnitPrice="12.34",
            PurchaseCost="5.67",
            IncomeAccountRef=Obj(value="income"),
            ExpenseAccountRef=Obj(value="expense"),
        )
    ]
    records["invoices"] = [
        Obj(
            Id="invoice",
            DocNumber="QBO-1",
            CustomerRef=Obj(value="customer"),
            TotalAmt="24.68",
            Balance="12.34",
            TxnDate="2026-01-01",
            DueDate="2026-01-31",
            TxnTaxDetail=Obj(TotalTax="0"),
            SalesTermRef={"name": "Net 15"},
            CustomerMemo={"value": "Invoice memo"},
            Line=[
                Obj(DetailType="SubTotalLineDetail"),
                Obj(DetailType="SalesItemLineDetail"),
                Obj(
                    DetailType="SalesItemLineDetail",
                    Amount="24.68",
                    Description="Work",
                    SalesItemLineDetail=Obj(
                        Qty=2, UnitPrice="12.34", ItemRef=Obj(value="item")
                    ),
                ),
            ],
        )
    ]
    records["payments"] = [
        Obj(
            Id="payment",
            CustomerRef=Obj(value="customer"),
            TotalAmt="12.34",
            TxnDate="2026-01-02",
            DepositToAccountRef=Obj(value="income"),
            PaymentMethodRef={"name": "Check"},
            PaymentRefNum="REF",
            Line=[
                Obj(Amount="12.34", LinkedTxn=[Obj(TxnType="Invoice", TxnId="invoice")])
            ],
        )
    ]


def test_full_import_preserves_links_and_source_balances(db_session, remote_import):
    records, _ = remote_import
    populate_remote(records)
    result = qbo_import.import_all(db_session)
    assert result == dict.fromkeys(ENTITIES, 1) | {
        "accounts": 2,
        "sales_receipts": 0,
        "journal_entries": 0,
        "ledger": 0,
        "errors": [],
    }
    accounts = {row.name: row for row in db_session.query(Account)}
    assert accounts["Expense"].parent_id == accounts["Income"].id
    customer = db_session.query(Customer).one()
    assert (customer.bill_address1, customer.ship_address2, customer.terms) == (
        "1 Test",
        "Suite 2",
        "Net 15",
    )
    assert (customer.email, customer.mobile, customer.website) == (
        "test@example.invalid",
        "556",
        "https://example.invalid",
    )
    assert db_session.query(Vendor).one().account_number == "VENDOR"
    item = db_session.query(Item).one()
    assert item.income_account_id == accounts["Income"].id
    assert item.expense_account_id == accounts["Expense"].id
    assert item.rate == Decimal("12.34")
    invoice = db_session.query(Invoice).one()
    assert invoice.customer_id == customer.id
    assert len(invoice.lines) == 1
    assert invoice.lines[0].item_id == item.id
    assert invoice.lines[0].amount == Decimal("24.68")
    assert invoice.amount_paid == Decimal("12.34")
    assert invoice.balance_due == Decimal("12.34")
    assert invoice.status == InvoiceStatus.PARTIAL
    payment = db_session.query(Payment).one()
    assert payment.amount == Decimal("12.34")
    assert payment.reference == "REF"
    assert db_session.query(PaymentAllocation).one().invoice_id == invoice.id
    assert db_session.query(QBOMapping).count() == 7
    assert qbo_import.import_all(db_session) == dict.fromkeys(ENTITIES, 0) | {
        "journal_entries": 0,
        "ledger": 0,
        "errors": []
    }


@pytest.mark.parametrize("kind", ENTITIES)
def test_query_failure_is_reported(db_session, remote_import, kind):
    remote_import[1].add(kind)
    result = getattr(qbo_import, f"import_{kind}")(db_session)
    assert result == {
        "imported": 0,
        "errors": [
            {
                "entity": kind,
                "message": "Failed to query QBO: unexpected error — the server log has the details",
            }
        ],
    }
    assert db_session.query(QBOMapping).count() == 0


@pytest.mark.parametrize(
    "kind,model",
    [
        ("accounts", Account),
        ("customers", Customer),
        ("vendors", Vendor),
        ("items", Item),
    ],
)
def test_false_flags_and_missing_identifiers(db_session, remote_import, kind, model):
    records, _ = remote_import
    records[kind] = [
        Obj(Id=None, Name="No ID", DisplayName="No ID"),
        Obj(Id="no-name"),
        Obj(
            Id="valid",
            Name="Inactive",
            DisplayName="Inactive",
            Active=False,
            Taxable=False,
        ),
    ]
    result = getattr(qbo_import, f"import_{kind}")(db_session)
    db_session.commit()
    assert result == {"imported": 1, "errors": []}
    row = db_session.query(model).one()
    assert row.is_active is False
    if hasattr(row, "is_taxable"):
        assert row.is_taxable is False


@pytest.mark.parametrize(
    "kind,model",
    [
        ("accounts", Account),
        ("customers", Customer),
        ("vendors", Vendor),
        ("items", Item),
    ],
)
def test_existing_name_maps_without_duplicate(db_session, remote_import, kind, model):
    records, _ = remote_import
    records[kind] = [Obj(Id="first", Name="Existing", DisplayName="Existing")]
    run = getattr(qbo_import, f"import_{kind}")
    assert run(db_session)["imported"] == 1
    records[kind] = [Obj(Id="second", Name="Existing", DisplayName="Existing")]
    assert run(db_session) == {"imported": 0, "errors": []}
    db_session.commit()
    assert db_session.query(model).count() == 1
    assert db_session.query(QBOMapping).count() == 2


@pytest.mark.parametrize("kind", ["invoices", "payments", "sales_receipts"])
def test_missing_customer_does_not_import_document(db_session, remote_import, kind):
    remote_import[0][kind] = [Obj(), Obj(Id="missing-customer")]
    result = getattr(qbo_import, f"import_{kind}")(db_session)
    assert result["imported"] == 0
    assert result["errors"][0]["message"].startswith(
        f"{kind[:-1]} QBO #missing-customer: Customer not found"
    )


@pytest.mark.parametrize(
    "value,expected", [(None, "0"), ("bad", "0"), ("12.34", "12.34")]
)
def test_decimal_conversion(value, expected):
    assert qbo_import._safe_decimal(Obj(value=value), "value") == Decimal(expected)


@pytest.mark.parametrize("value", [None, "invalid-date", "2026-99-99"])
def test_invalid_dates_use_import_date(value):
    assert qbo_import._parse_qbo_date(value) == date.today()


@pytest.mark.parametrize(
    "balance,status",
    [
        ("24.68", InvoiceStatus.SENT),
        ("0", InvoiceStatus.PAID),
        ("30", InvoiceStatus.SENT),
    ],
)
def test_invoice_status_comes_from_snapshot(db_session, remote_import, balance, status):
    records, _ = remote_import
    populate_remote(records)
    records["invoices"][0].Balance = balance
    records["payments"] = []
    assert qbo_import.import_all(db_session)["errors"] == []
    invoice = db_session.query(Invoice).one()
    assert invoice.status == status
    assert invoice.balance_due == Decimal(balance)
    assert invoice.amount_paid == Decimal("24.68") - Decimal(balance)


@pytest.mark.parametrize("kind", ["invoices", "payments", "sales_receipts"])
def test_documents_resolve_customer_by_name(db_session, remote_import, kind):
    db_session.add(Customer(name="Local customer"))
    db_session.commit()
    remote_import[0][kind] = [
        Obj(
            Id="document",
            DocNumber="LOCAL-1",
            CustomerRef=Obj(name="Local customer"),
            TotalAmt="10",
            Balance="10",
            TxnDate="2026-01-01",
        )
    ]
    assert getattr(qbo_import, f"import_{kind}")(db_session) == {
        "imported": 1,
        "errors": [],
    }
    db_session.commit()
    assert db_session.query(QBOMapping).one().qbo_id == "document"


@pytest.mark.parametrize("kind", ["invoices", "sales_receipts"])
def test_existing_document_number_maps_without_duplicate(
    db_session, remote_import, kind
):
    customer = Customer(name="Existing")
    db_session.add(customer)
    db_session.flush()
    db_session.add(
        Invoice(
            invoice_number="EXISTING", customer_id=customer.id, date=date(2026, 1, 1)
        )
    )
    db_session.commit()
    remote_import[0][kind] = [Obj(Id="document", DocNumber="EXISTING")]
    assert getattr(qbo_import, f"import_{kind}")(db_session) == {
        "imported": 0,
        "errors": [],
    }
    assert db_session.query(Invoice).count() == 1
    assert db_session.query(QBOMapping).one().qbo_id == "document"


@pytest.mark.parametrize("kind", ENTITIES)
def test_unreadable_remote_record_is_reported(db_session, remote_import, kind):
    field = (
        "Name"
        if kind in ("accounts", "items")
        else "DisplayName" if kind in ("customers", "vendors") else "CustomerRef"
    )

    class Unreadable(Obj):
        def __getattribute__(self, name):
            if name == field:
                raise ValueError("synthetic malformed field")
            return super().__getattribute__(name)

    remote_import[0][kind] = [Unreadable(Id="bad-record")]
    result = getattr(qbo_import, f"import_{kind}")(db_session)
    assert result["imported"] == 0
    assert result["errors"][0]["qbo_id"] == "bad-record"
    assert result["errors"][0]["message"].endswith(
        "unexpected error — the server log has the details"
    )
    assert db_session.query(QBOMapping).count() == 0


@pytest.mark.parametrize(
    "parent_ref", [Obj(value="parent"), "parent", Obj(value="unmapped")]
)
def test_subcustomer_is_imported_as_job(db_session, remote_import, parent_ref):
    from app.models.jobs import Job

    remote_import[0]["customers"] = [
        Obj(
            Id="child",
            DisplayName="Project",
            FullyQualifiedName="Parent:Project",
            Job=True,
            ParentRef=parent_ref,
        ),
        Obj(Id="parent", DisplayName="Parent"),
    ]
    assert qbo_import.import_customers(db_session) == {"imported": 2, "errors": []}
    db_session.commit()
    job = db_session.query(Job).one()
    assert job.customer_id == db_session.query(Customer).one().id
    assert job.name == "Project"
    assert qbo_import.import_customers(db_session) == {"imported": 0, "errors": []}


def test_sales_receipt_preserves_item_and_deposit_references(db_session, remote_import):
    records, _ = remote_import
    populate_remote(records)
    records["sales_receipts"] = [
        Obj(
            Id="receipt",
            CustomerRef=Obj(value="customer"),
            TotalAmt="24.68",
            DepositToAccountRef=Obj(value="income"),
            Line=records["invoices"][0].Line,
        )
    ]
    assert qbo_import.import_all(db_session)["errors"] == []
    receipt = db_session.query(Invoice).filter_by(is_sales_receipt=True).one()
    assert receipt.invoice_number
    assert receipt.lines[0].item_id == db_session.query(Item).one().id
    payment = db_session.query(Payment).filter_by(amount=Decimal("24.68")).one()
    assert (
        payment.deposit_to_account_id
        == db_session.query(Account).filter_by(name="Income").one().id
    )
    assert qbo_import.import_sales_receipts(db_session) == {"imported": 0, "errors": []}
