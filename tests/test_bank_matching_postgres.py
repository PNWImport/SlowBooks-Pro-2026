"""Real row-lock behavior using independent PostgreSQL connections."""

from datetime import date

import pytest
from fastapi import HTTPException

from app.models.accounts import Account, AccountType
from app.models.banking import BankAccount, BankTransaction
from app.models.transactions import Transaction, TransactionLine
from app.services import bank_matching as matching
from tests.test_accounting_concurrency import accounting_sessions  # noqa: F401


@pytest.fixture
def banking_sessions(accounting_sessions):  # noqa: F811 - imported pytest fixture
    factory = accounting_sessions
    with factory() as db:
        if db.bind.dialect.name != "postgresql":
            pytest.skip("Row-lock acceptance requires PostgreSQL")
        db.add_all(
            [
                Account(
                    id=1, name="Bank", account_type=AccountType.ASSET, bank_kind="bank"
                ),
                Account(id=2, name="Expense", account_type=AccountType.EXPENSE),
            ]
        )
        db.flush()
        db.add(BankAccount(id=1, name="Feed", account_id=1))
        txn = Transaction(id=1, date=date(2026, 9, 1), source_type="manual")
        db.add(txn)
        db.flush()
        db.add_all(
            [
                TransactionLine(
                    id=1, transaction_id=1, account_id=1, debit=0, credit=10
                ),
                TransactionLine(
                    id=2, transaction_id=1, account_id=2, debit=10, credit=0
                ),
                BankTransaction(
                    id=1,
                    bank_account_id=1,
                    date=date(2026, 9, 1),
                    amount=-10,
                    match_status="unmatched",
                    category_account_id=2,
                ),
            ]
        )
        db.commit()
    return factory


@pytest.mark.parametrize("operation", ["match", "unmatch", "auto"])
def test_locked_ledger_row_never_waits_while_holding_statement(
    banking_sessions, operation
):
    with banking_sessions() as holder, banking_sessions() as worker:
        if operation == "unmatch":
            statement = holder.get(BankTransaction, 1)
            matching.match(holder, statement, 1)
            holder.commit()
        holder.query(TransactionLine).filter_by(id=1).with_for_update().one()
        statement = (
            worker.query(BankTransaction).filter_by(id=1).with_for_update().one()
        )
        if operation == "auto":
            assert (
                matching.auto_match(worker, worker.get(BankAccount, 1), [statement])
                == 0
            )
        else:
            with pytest.raises(HTTPException) as exc:
                if operation == "match":
                    matching.match(worker, statement, 1)
                else:
                    matching.unmatch(worker, statement)
            assert exc.value.status_code == 409
        assert statement.transaction_line_id == (1 if operation == "unmatch" else None)
        worker.rollback()
        holder.rollback()


@pytest.mark.parametrize("operation", ["auto", "add_all"])
def test_batch_skips_another_workers_statement_claim(banking_sessions, operation):
    with banking_sessions() as holder, banking_sessions() as worker:
        holder.query(BankTransaction).filter_by(id=1).with_for_update().one()
        feed = worker.get(BankAccount, 1)
        if operation == "auto":
            assert (
                matching.auto_match(worker, feed, [worker.get(BankTransaction, 1)]) == 0
            )
        else:
            assert matching.add_all(worker, feed) == {"added": 0, "skipped": []}
        assert worker.get(BankTransaction, 1).transaction_line_id is None
        assert worker.query(Transaction).count() == 1
        worker.rollback()
        holder.rollback()
