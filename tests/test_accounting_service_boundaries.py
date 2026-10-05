"""Accounting helper contracts and rejection paths using real database rows."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.accounts import Account, AccountType
from app.models.cost_codes import CostCode
from app.models.transactions import Transaction, TransactionLine
from app.services import accounting


@pytest.mark.parametrize(
    "terms,days",
    [(None, 30), ("", 30), ("Net 15", 15), (" NET 60 ", 60), ("invalid", 30), ("0", 0)],
)
def test_due_dates_cross_year_boundary(terms, days):
    from datetime import timedelta

    start = date(2026, 12, 20)
    assert accounting.due_date_from_terms(start, terms) == start + timedelta(days=days)
    assert accounting.due_date_from_terms(
        start, "invalid", default_days=7
    ) == start + timedelta(days=7)


def test_quantization_and_tax_flags_preserve_line_sum():
    assert accounting.quantize_to("1.23455", Decimal("0.0001")) == Decimal("1.2346")
    assert accounting.quantize_cents(None) == Decimal("0.00")
    lines = [
        SimpleNamespace(quantity=1, rate="1.005"),
        SimpleNamespace(quantity=1, rate="1.005", is_taxable=None),
        SimpleNamespace(quantity=1, rate="1.005", is_taxable=False),
    ]
    assert accounting.compute_line_totals(iter(lines), "0.10") == (
        Decimal("3.03"),
        Decimal("0.20"),
        Decimal("3.23"),
    )


@pytest.mark.parametrize(
    "getter,number",
    [
        ("get_ar_account_id", "1100"),
        ("get_default_income_account_id", "4000"),
        ("get_sales_tax_account_id", "2200"),
        ("get_undeposited_funds_id", "1200"),
        ("get_ap_account_id", "2000"),
        ("get_cc_account_id", "2100"),
    ],
)
def test_account_lookup_missing_and_present(db_session, getter, number):
    lookup = getattr(accounting, getter)
    from app.services.control_accounts import MissingControlAccount

    with pytest.raises(MissingControlAccount):
        lookup(db_session)
    account = Account(
        name="Synthetic", account_number=number, account_type=AccountType.ASSET
    )
    db_session.add(account)
    db_session.commit()
    assert lookup(db_session) == account.id


def test_system_accounts_preserve_imported_number_and_are_idempotent(db_session):
    imported = Account(
        name="Imported equity", account_number="3300", account_type=AccountType.EQUITY
    )
    db_session.add(imported)
    db_session.commit()
    accounts = accounting.ensure_nonprofit_accounts(db_session)
    assert accounts["3300"].account_number is None
    assert imported.account_number == "3300"
    for key, getter in [
        ("3300", "get_net_assets_without_restriction_id"),
        ("3400", "get_net_assets_with_restriction_id"),
        ("4400", "get_in_kind_income_account_id"),
        ("6960", "get_bad_debt_account_id"),
    ]:
        assert getattr(accounting, getter)(db_session) == accounts[key].id
    db_session.commit()
    assert db_session.query(Account).count() == 5


def test_cost_code_lookup_missing_and_present(db_session):
    assert accounting._cost_type_of(db_session, None) is None
    assert accounting._cost_type_of(db_session, 999999) is None
    code = CostCode(code="SYN", name="Synthetic labor", cost_type="labor")
    db_session.add(code)
    db_session.commit()
    assert accounting._cost_type_of(db_session, code.id) == "labor"


@pytest.mark.parametrize(
    "lines,message",
    [
        ([{"account_id": 1, "debit": -1}], "non-negative"),
        ([{"account_id": 1, "debit": 1, "credit": 1}], "both debit and credit"),
        ([{"account_id": 1, "debit": 1}], "out of balance"),
    ],
)
def test_invalid_lines_leave_no_partial_journal(db_session, lines, message):
    with pytest.raises(ValueError, match=message):
        accounting.create_journal_entry(db_session, date(2026, 1, 1), "Invalid", lines)
    assert db_session.query(Transaction).count() == 0
    assert db_session.query(TransactionLine).count() == 0


def test_reversal_preserves_dimensions_and_explicit_function():
    original = SimpleNamespace(
        account_id=1,
        credit=Decimal("2"),
        debit=Decimal("0"),
        description=None,
        job_id=3,
        class_id=4,
        cost_code_id=5,
        cost_type="labor",
        function="program",
    )
    assert accounting.reversing_lines([original]) == [
        {
            "account_id": 1,
            "debit": Decimal("2"),
            "credit": Decimal("0"),
            "description": "VOID: ",
            "job_id": 3,
            "class_id": 4,
            "cost_code_id": 5,
            "cost_type": "labor",
            "function": "program",
        }
    ]


def test_zero_placeholder_skipped_and_explicit_function_retained(
    db_session, seed_accounts
):
    debit, credit = seed_accounts["1100"], seed_accounts["4000"]
    txn = accounting.create_journal_entry(
        db_session,
        date(2026, 1, 1),
        "Synthetic",
        [
            {"account_id": debit.id, "debit": 10, "function": "program"},
            {"account_id": credit.id, "credit": 10, "function": None},
            {"account_id": debit.id, "debit": 0, "credit": 0},
        ],
    )
    db_session.commit()
    assert len(txn.lines) == 2
    assert {line.function for line in txn.lines} == {None, "program"}
    assert debit.balance == credit.balance == Decimal("10")
