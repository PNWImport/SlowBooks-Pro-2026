from datetime import date
from decimal import Decimal

import pytest

from app.models.accounts import Account, AccountType
from app.services import migration_common
from app.services.migration_common import (
    dry_run_bundle,
    make_classifier,
    parse_amount,
    parse_date,
    skip_report_preamble,
)


def test_invalid_amount_and_date_report_the_source_value():
    with pytest.raises(ValueError, match="unparseable amount"):
        parse_amount("not-money")
    with pytest.raises(ValueError, match="unparseable date"):
        parse_date("not-a-date", ("%Y-%m-%d", "%m/%d/%Y"))


def test_classifier_and_preamble_fallbacks_leave_unknown_input_alone():
    assert make_classifier()("notes.txt") is None
    text = "Company Name\nReport without a table header"
    assert skip_report_preamble(text) == text


def test_dry_run_reports_unknown_account_only_once(db_session):
    rows = [
        {
            "date": date(2026, 9, 13),
            "account": "Missing (9999)",
            "debit": Decimal("1"),
            "credit": Decimal("0"),
            "reference": "J1",
        },
        {
            "date": date(2026, 9, 13),
            "account": "Missing (9999)",
            "debit": Decimal("0"),
            "credit": Decimal("1"),
            "reference": "J1",
        },
    ]
    parsers = {
        "coa": lambda text: ([], []),
        "gl": lambda text: ([rows], []),
    }
    result = dry_run_bundle(
        db_session, {"coa": "chart", "gl": "journal"}, parsers, "Test"
    )
    missing = [error for error in result["errors"] if "not present" in error]
    assert len(missing) == 1


def test_import_skips_duplicates_collisions_empty_rows_and_opening_noise(
    db_session, monkeypatch
):
    existing = Account(
        name="Existing", account_number="1000", account_type=AccountType.ASSET
    )
    db_session.add(existing)
    db_session.commit()
    specs = [
        {
            "name": "Existing",
            "code": "2000",
            "type": AccountType.ASSET,
            "description": "duplicate name",
        },
        {
            "name": "New",
            "code": "1000",
            "type": AccountType.EXPENSE,
            "description": "colliding code",
        },
    ]
    day = date(2026, 9, 13)
    journals = [
        [
            {
                "date": day,
                "account": "New",
                "debit": Decimal("0"),
                "credit": Decimal("-5"),
            },
            {
                "date": day,
                "account": "New",
                "debit": Decimal("0"),
                "credit": Decimal("0"),
            },
        ],
        [
            {
                "date": day,
                "account": "New",
                "debit": Decimal("0"),
                "credit": Decimal("0"),
            }
        ],
    ]
    verdict = {
        "ok": True,
        "errors": [],
        "warnings": [],
        "opening_balances": [
            {"account": "missing", "amount": 1},
            {"account": "new", "amount": 0},
        ],
    }
    monkeypatch.setattr(migration_common, "dry_run_bundle", lambda *args: verdict)
    posted = []
    monkeypatch.setattr(
        migration_common,
        "create_journal_entry",
        lambda *args, **kwargs: posted.append((args, kwargs)),
    )
    parsers = {
        "coa": lambda text: (specs, []),
        "gl": lambda text: (journals, []),
    }

    result = migration_common.run_import_bundle(
        db_session,
        {"coa": "chart", "gl": "journal"},
        parsers,
        "test_import",
        "Test",
    )
    assert result["imported_accounts"] == 1
    assert result["imported_journals"] == 1
    assert db_session.query(Account).filter_by(name="New").one().account_number is None
    assert posted[0][0][3][0]["debit"] == Decimal("5.00")
