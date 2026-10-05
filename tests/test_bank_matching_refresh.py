"""Stale-candidate and lock/refresh contracts, not live concurrency acceptance."""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Query

from app.models.banking import BankAccount, BankTransaction, Reconciliation
from app.models.transactions import TransactionLine
from app.services import bank_matching as matching
from tests.test_bank_void_locking import posting


@pytest.fixture
def context(db_session, seed_accounts):
    txn = posting(db_session, seed_accounts, "manual")
    feed = BankAccount(name="Refresh feed", account_id=seed_accounts["1000"].id)
    db_session.add(feed)
    db_session.flush()
    statement = BankTransaction(
        bank_account_id=feed.id,
        date=date(2026, 9, 1),
        amount=-10,
        match_status="unmatched",
    )
    recon = Reconciliation(
        account_id=feed.account_id,
        statement_date=date(2026, 9, 30),
        statement_balance=-10,
    )
    db_session.add_all([statement, recon])
    db_session.commit()
    line = next(ln for ln in txn.lines if ln.account_id == feed.account_id)
    return feed, statement, line, recon


@pytest.mark.parametrize("change", ["reconciled", "claimed", "amount"])
def test_auto_match_revalidates_candidate_before_linking(
    db_session, context, monkeypatch, change
):
    feed, statement, line, recon = context
    original = matching.candidate_lines

    def stale_candidates(*args, **kwargs):
        result = original(*args, **kwargs)
        assert [row["line_id"] for row in result] == [line.id]
        if change == "claimed":
            db_session.add(
                BankTransaction(
                    bank_account_id=feed.id,
                    date=statement.date,
                    amount=-10,
                    match_status="manual",
                    transaction_line_id=line.id,
                    transaction_id=line.transaction_id,
                )
            )
            db_session.flush()
        else:
            values = (
                {"reconciliation_id": recon.id}
                if change == "reconciled"
                else {"credit": 11}
            )
            db_session.execute(
                TransactionLine.__table__.update()
                .where(TransactionLine.id == line.id)
                .values(**values)
            )
        return result

    monkeypatch.setattr(matching, "candidate_lines", stale_candidates)
    assert matching.auto_match(db_session, feed, [statement]) == 0
    assert statement.transaction_line_id is None
    assert statement.match_status == "unmatched"


def test_auto_match_does_not_overwrite_stale_statement_decision(db_session, context):
    feed, statement, line, recon = context
    assert statement.match_status == "unmatched"
    db_session.execute(
        BankTransaction.__table__.update()
        .where(BankTransaction.id == statement.id)
        .values(match_status="excluded")
    )
    assert matching.auto_match(db_session, feed, [statement]) == 0
    db_session.refresh(statement)
    assert statement.match_status == "excluded"
    assert statement.transaction_line_id is None


@pytest.mark.parametrize("operation", ["auto", "add_all"])
def test_batch_claims_use_skip_locked_rows(db_session, context, monkeypatch, operation):
    feed, statement, line, recon = context
    statement.category_account_id = next(
        ln.account_id for ln in line.transaction.lines if ln.id != line.id
    )
    db_session.commit()
    original = Query.with_for_update
    claims = []

    def spy(query, *args, **kwargs):
        if query.column_descriptions[0].get("entity") is BankTransaction:
            claims.append(kwargs.get("skip_locked"))
        return original(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", spy)
    if operation == "auto":
        assert matching.auto_match(db_session, feed, [statement]) == 1
    else:
        assert matching.add_all(db_session, feed)["added"] == 1
    assert claims == [True]


@pytest.mark.parametrize("operation", ["match", "unmatch"])
def test_match_mutations_refresh_reconciliation_state_under_lock(
    db_session, context, monkeypatch, operation
):
    feed, statement, line, recon = context
    if operation == "unmatch":
        matching.match(db_session, statement, line.id)
        db_session.commit()
    assert line.reconciliation_id is None
    original = Query.with_for_update
    locks = []

    def changed_after_wait(query, *args, **kwargs):
        if query.column_descriptions[0].get("entity") is TransactionLine:
            locks.append(line.id)
            db_session.execute(
                TransactionLine.__table__.update()
                .where(TransactionLine.id == line.id)
                .values(reconciliation_id=recon.id)
            )
        return original(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", changed_after_wait)
    with pytest.raises(HTTPException, match="completed reconciliation"):
        if operation == "match":
            matching.match(db_session, statement, line.id)
        else:
            matching.unmatch(db_session, statement)
    assert locks == [line.id]
    assert statement.transaction_line_id == (
        line.id if operation == "unmatch" else None
    )
    assert bool(line.cleared) == (operation == "unmatch")


@pytest.mark.parametrize("operation", ["match", "unmatch", "auto"])
def test_busy_ledger_line_is_not_waited_on_or_changed(
    db_session, context, monkeypatch, operation
):
    feed, statement, line, recon = context
    if operation == "unmatch":
        matching.match(db_session, statement, line.id)
        db_session.commit()
    original = Query.first
    lock_options = []

    def simulate_busy(query):
        lock = query._for_update_arg
        if (
            lock is not None
            and query.column_descriptions[0].get("entity") is TransactionLine
        ):
            lock_options.append(lock.skip_locked)
            return None
        return original(query)

    monkeypatch.setattr(Query, "first", simulate_busy)
    if operation == "auto":
        assert matching.auto_match(db_session, feed, [statement]) == 0
    else:
        with pytest.raises(HTTPException) as exc:
            if operation == "match":
                matching.match(db_session, statement, line.id)
            else:
                matching.unmatch(db_session, statement)
        assert exc.value.status_code == 409
    assert lock_options == [True]
    assert statement.transaction_line_id == (
        line.id if operation == "unmatch" else None
    )
    assert bool(line.cleared) == (operation == "unmatch")
