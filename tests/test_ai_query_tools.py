"""AI tool results must reflect real rows, filters, and financial signs."""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import event

from app.models.accounts import Account, AccountType
from app.models.bills import Bill, BillLine, BillPayment
from app.models.contacts import Customer, Vendor
from app.models.invoices import Invoice
from app.models.payments import Payment
from app.models.transactions import Transaction
from app.services import ai_tools as ai


@pytest.fixture
def query_rows(db_session):
    customer = Customer(name="Synthetic Customer", email="customer@example.invalid")
    vendor = Vendor(name="Synthetic Vendor", email="vendor@example.invalid")
    expense = Account(
        name="Supplies",
        account_number="6000",
        account_type=AccountType.EXPENSE,
        balance=30,
    )
    db_session.add_all([customer, vendor, expense])
    db_session.flush()
    today = date.today()
    for i, days in enumerate([0, 31, 61, 91]):
        day = today - timedelta(days=days)
        bill = Bill(
            bill_number=f"B-{i}",
            vendor_id=vendor.id,
            date=day,
            total=10,
            balance_due=10,
        )
        db_session.add(bill)
        db_session.flush()
        db_session.add_all(
            [
                BillLine(bill_id=bill.id, account_id=expense.id, amount=10),
                Invoice(
                    invoice_number=f"I-{i}",
                    customer_id=customer.id,
                    date=day,
                    total=20,
                    balance_due=20,
                    tax_amount=2,
                ),
                Payment(
                    customer_id=customer.id, date=day, amount=5, reference=f"P-{i}"
                ),
                BillPayment(
                    vendor_id=vendor.id, date=day, amount=5, check_number=f"C-{i}"
                ),
                Transaction(
                    date=day, description="Synthetic journal", reference=f"J-{i}"
                ),
            ]
        )
    db_session.commit()
    return expense


SEARCHES = [
    ("search_bills", {"vendor_name": "synthetic", "status": "unpaid"}),
    ("search_invoices", {"customer_name": "synthetic", "status": "draft"}),
    ("search_transactions", {"description": "synthetic"}),
    ("search_payments", {"customer_name": "synthetic"}),
    ("search_bill_payments", {"vendor_name": "synthetic"}),
]


@pytest.mark.parametrize("name,params", SEARCHES)
def test_search_filters_and_serialization(db_session, query_rows, name, params):
    today = date.today().isoformat()
    result = ai.call_tool(name, db_session, start_date=today, end_date=today, **params)
    assert result["count"] == 1
    assert result["results"][0]["date"] == today
    json.dumps(result)
    assert ai.call_tool(name, db_session, limit=2)["count"] == 2
    assert (
        ai.call_tool(name, db_session, start_date="1900-01-01", end_date="1900-01-02")[
            "count"
        ]
        == 0
    )


@pytest.mark.parametrize("name,params", SEARCHES)
def test_invalid_search_dates_do_not_crash(db_session, query_rows, name, params):
    assert (
        ai.call_tool(name, db_session, start_date="bad", end_date="bad", **params)[
            "count"
        ]
        == 4
    )


@pytest.mark.parametrize(
    "name,filter_name,filter_value",
    [
        ("list_customers", "name_filter", "Customer"),
        ("list_vendors", "name_filter", "Vendor"),
        ("list_accounts", "account_type", "expense"),
    ],
)
def test_lists_apply_filters(db_session, query_rows, name, filter_name, filter_value):
    result = ai.call_tool(name, db_session, **{filter_name: filter_value})
    assert result["count"] == 1
    assert result["results"][0]["name"]
    json.dumps(result)


def test_account_balance_and_missing_account(db_session, query_rows):
    result = ai.get_account_balance(db_session, query_rows.id)
    assert result["balance"] == 30
    assert result["account_type"] == "expense"
    assert ai.get_account_balance(db_session, -1)["balance"] is None
    assert ai._to_float(None) is None


def test_pl_does_not_turn_negative_income_into_profit(db_session):
    db_session.add_all(
        [
            Account(
                name="Returns exceed sales",
                account_type=AccountType.INCOME,
                balance=-10,
            ),
            Account(name="Expenses", account_type=AccountType.EXPENSE, balance=3),
            Account(name="Cost", account_type=AccountType.COGS, balance=2),
        ]
    )
    db_session.commit()
    assert ai.get_pl_summary(db_session) == {
        "total_income": -10,
        "total_expense": 3,
        "total_cogs": 2,
        "net_income": -15,
    }


def test_balance_sheet_equation(db_session):
    db_session.add_all(
        [
            Account(name="Assets", account_type=AccountType.ASSET, balance=120),
            Account(name="Liabilities", account_type=AccountType.LIABILITY, balance=20),
            Account(name="Equity", account_type=AccountType.EQUITY, balance=100),
        ]
    )
    db_session.commit()
    assert ai.get_balance_sheet(db_session) == {
        "total_assets": 120,
        "total_liabilities": 20,
        "total_equity": 100,
        "accounting_equation_balanced": True,
    }


def test_tax_summary_applies_period_to_expenses_too(db_session, query_rows):
    today = date.today().isoformat()
    result = ai.get_tax_summary(db_session, start_date=today, end_date=today)
    assert result == {
        "total_tax_collected": 2,
        "expenses_by_account": {"6000 Supplies": 10},
    }


@pytest.mark.parametrize(
    "name", ["get_tax_summary", "get_sales_by_customer", "get_expenses_by_category"]
)
def test_summary_invalid_dates_and_valid_period(db_session, query_rows, name):
    result = ai.call_tool(name, db_session, start_date="bad", end_date="bad")
    assert "error" not in result
    json.dumps(result)
    today = date.today().isoformat()
    filtered = ai.call_tool(name, db_session, start_date=today, end_date=today)
    if name == "get_sales_by_customer":
        assert filtered == {
            "results": [{"customer": "Synthetic Customer", "total_sales": 20}],
            "total": 20,
        }
    elif name == "get_expenses_by_category":
        assert filtered == {
            "results": [{"category": "6000 Supplies", "total_expenses": 10}],
            "total": 10,
        }


def test_aging_covers_each_bucket(db_session, query_rows):
    result = ai.get_aging_report(db_session)
    assert result["ar_aging"] == dict.fromkeys(["current", "30", "60", "90"], 20)
    assert result["ap_aging"] == dict.fromkeys(["current", "30", "60", "90"], 10)
    assert result["total_ar_outstanding"] == 80
    assert result["total_ap_outstanding"] == 40


def test_all_tools_are_serializable_and_read_only(db_session, query_rows):
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        for name in ai.TOOLS:
            params = (
                {"account_id": query_rows.id} if name == "get_account_balance" else {}
            )
            result = ai.call_tool(name, db_session, **params)
            assert "error" not in result, (name, result)
            json.dumps(result)
            schema = ai.get_tool_schema(name)
            assert schema["name"] == name
            assert "func" not in schema
            json.dumps(schema)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert statements and set(statements) == {"SELECT"}
    assert not db_session.new and not db_session.dirty and not db_session.deleted


def test_unknown_tool_and_argument_failure_are_safe(db_session):
    assert ai.get_tool_schema("unknown") is None
    assert ai.call_tool("unknown", db_session) == {"error": "Unknown tool: unknown"}
    result = ai.call_tool(
        "get_account_balance", db_session, injected="synthetic-sensitive-value"
    )
    assert result == {"error": "get_account_balance failed: TypeError"}
