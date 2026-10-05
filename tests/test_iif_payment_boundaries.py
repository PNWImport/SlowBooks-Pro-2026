"""IIF payment imports preserve customer ownership, deduplication, and journals."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.contacts import Customer
from app.models.invoices import Invoice, InvoiceStatus
from app.models.payments import Payment, PaymentAllocation
from app.models.transactions import Transaction
from app.services import iif_import as iif


def block(name="Synthetic", amount="10", invoice="IIF-1", reference="REF"):
    return {
        "trns": {
            "TRNSTYPE": "PAYMENT",
            "NAME": name,
            "AMOUNT": amount,
            "DATE": "01/01/2026",
            "DOCNUM": reference,
            "ACCNT": "Unmapped deposit name",
        },
        "spl": [{"DOCNUM": invoice, "AMOUNT": amount}],
    }


@pytest.fixture
def invoice(db_session):
    customer = Customer(name="Synthetic")
    db_session.add(customer)
    db_session.flush()
    invoice = Invoice(
        invoice_number="IIF-1",
        customer_id=customer.id,
        date=date(2026, 1, 1),
        total=20,
        amount_paid=0,
        balance_due=20,
    )
    db_session.add(invoice)
    db_session.commit()
    return invoice


@pytest.mark.parametrize(
    "amount,status,balance",
    [("10", InvoiceStatus.PARTIAL, "10"), ("20", InvoiceStatus.PAID, "0")],
)
def test_payment_allocation_and_journal(
    db_session, seed_accounts, invoice, amount, status, balance
):
    result = iif.import_transactions(db_session, [block(amount=amount)])
    db_session.commit()
    assert result["errors"] == []
    assert result["imported"]["payments"] == 1
    assert invoice.status == status and invoice.balance_due == Decimal(balance)
    payment = db_session.query(Payment).one()
    assert payment.deposit_to_account.account_number == "1200"
    assert payment.transaction_id
    journal = db_session.get(Transaction, payment.transaction_id)
    assert (
        sum(line.debit for line in journal.lines)
        == sum(line.credit for line in journal.lines)
        == Decimal(amount)
    )
    assert db_session.query(PaymentAllocation).one().amount == Decimal(amount)
    assert (
        iif.import_transactions(db_session, [block(amount=amount)])["imported"][
            "payments"
        ]
        == 0
    )


def test_payment_cannot_pay_another_customers_invoice(
    db_session, seed_accounts, invoice
):
    db_session.add(Customer(name="Other customer"))
    db_session.commit()
    result = iif.import_transactions(db_session, [block(name="Other customer")])
    assert result["imported"]["payments"] == 0
    assert len(result["errors"]) == 1
    assert db_session.query(Payment).count() == 0
    assert db_session.query(PaymentAllocation).count() == 0
    db_session.refresh(invoice)
    assert invoice.balance_due == Decimal("20")


def test_job_qualified_customer_payment_is_deduplicated(
    db_session, seed_accounts, invoice
):
    from app.models.jobs import Job

    db_session.add(Job(customer_id=invoice.customer_id, name="Project"))
    db_session.commit()
    data = block(name="Synthetic:Project")
    assert iif.import_transactions(db_session, [data])["imported"]["payments"] == 1
    db_session.commit()
    assert iif.import_transactions(db_session, [data])["imported"]["payments"] == 0
    assert db_session.query(Payment).count() == 1


def test_missing_customer_is_not_created_by_payment(db_session, seed_accounts):
    result = iif.import_transactions(db_session, [block(name="Missing")])
    assert result["imported"]["payments"] == 0
    assert db_session.query(Customer).count() == 0


def test_payment_without_chart_reports_missing_journal(db_session, invoice):
    result = iif.import_transactions(db_session, [block()])
    assert result["imported"]["payments"] == 1
    assert "journal entry could not be created" in result["warnings"][0]


def test_parser_recovers_unclosed_blocks_and_short_rows():
    content = "!CUST\tNAME\tEMAIL\r\nCUST\tSynthetic\r!TRNS\tTRNSTYPE\rTRNS\tINVOICE\rTRNS\tPAYMENT\rSPL\tignored\r"
    parsed = iif.parse_iif(content)
    assert parsed["CUST"][0]["EMAIL"] == ""
    assert [row["trns"]["TRNSTYPE"] for row in parsed["TRNS"]] == ["INVOICE", "PAYMENT"]


@pytest.mark.parametrize(
    "text,expected", [('"1,234.56"', "1234.56"), ('""', "0"), ("bad", "0")]
)
def test_decimal_input_formats(text, expected):
    assert iif._parse_decimal(text) == Decimal(expected)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", ("", "", "")),
        ("Test, WA 00000", ("Test", "WA", "00000")),
        ("Test, WA", ("Test", "WA", "")),
        ("Test", ("Test", "", "")),
    ],
)
def test_address_formats(text, expected):
    assert iif._parse_city_state_zip(text) == expected


def test_account_lookup_fallbacks(db_session, seed_accounts):
    assert iif._find_account(db_session, "") is None
    assert iif._find_account(db_session, "A/R").account_number == "1100"
    assert iif._find_account(db_session, "accounts receivable").account_number == "1100"
    assert iif._find_account(db_session, "No such account") is None
