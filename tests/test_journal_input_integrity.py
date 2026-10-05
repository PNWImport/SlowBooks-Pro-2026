"""Invalid journal inputs must fail before creating a header or changing balances."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.accounts import Account, AccountType
from app.models.transactions import Transaction, TransactionLine
from app.services.accounting import create_journal_entry


def test_missing_account_rejected_before_any_journal_write(db_session):
    account = Account(name="Synthetic bank", account_type=AccountType.ASSET, balance=0)
    db_session.add(account)
    db_session.commit()
    with pytest.raises(ValueError, match="account.*not found"):
        create_journal_entry(
            db_session,
            date.today(),
            "Invalid account",
            [
                {"account_id": account.id, "debit": 10},
                {"account_id": 999999, "credit": 10},
            ],
        )
    assert db_session.query(Transaction).count() == 0
    assert db_session.query(TransactionLine).count() == 0
    assert account.balance == 0


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_amounts_rejected_before_writes(db_session, amount):
    with pytest.raises(ValueError, match="finite"):
        create_journal_entry(
            db_session,
            date.today(),
            "Invalid amount",
            [
                {"account_id": 1, "debit": Decimal(amount)},
                {"account_id": 2, "credit": Decimal(amount)},
            ],
        )
    assert db_session.query(Transaction).count() == 0
