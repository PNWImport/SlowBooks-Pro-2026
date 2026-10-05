"""Lock/refresh contracts; SQLite tests do not establish concurrent-write safety."""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Query

from app.models.banking import Reconciliation, ReconciliationStatus
from app.models.transactions import Transaction, TransactionLine
from app.services.accounting import create_journal_entry
from app.services.bank_posting import assert_not_reconciled


def posting(db, accounts, source):
    txn = create_journal_entry(
        db,
        date(2026, 9, 1),
        "Void lock regression",
        [
            {"account_id": accounts["6000"].id, "debit": 10, "credit": 0},
            {"account_id": accounts["1000"].id, "debit": 0, "credit": 10},
        ],
        source_type=source,
    )
    db.commit()
    return txn


@pytest.mark.parametrize(
    "source,route", [("expense", "expenses"), ("manual", "journal")]
)
def test_separate_void_routes_lock_ledger_lines(
    client, db_session, seed_accounts, monkeypatch, source, route
):
    txn = posting(db_session, seed_accounts, source)
    locked = []
    original = Query.with_for_update

    def spy(query, *args, **kwargs):
        locked.append(query.column_descriptions[0].get("entity"))
        return original(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", spy)
    response = client.post(f"/api/{route}/{txn.id}/void")
    assert response.status_code == 200, response.text
    assert Transaction in locked
    assert TransactionLine in locked


def test_void_guard_refreshes_cached_lines_after_obtaining_lock(
    db_session, seed_accounts, monkeypatch
):
    txn = posting(db_session, seed_accounts, "manual")
    recon = Reconciliation(
        account_id=seed_accounts["1000"].id,
        statement_date=date(2026, 9, 30),
        statement_balance=-10,
        status=ReconciliationStatus.COMPLETED,
    )
    db_session.add(recon)
    db_session.commit()
    line = next(ln for ln in txn.lines if ln.account_id == seed_accounts["1000"].id)
    assert line.reconciliation_id is None
    original = Query.with_for_update
    refreshed = []

    def simulate_completed_reconciliation(query, *args, **kwargs):
        # Change the DB without updating the ORM identity map, as a waiter
        # would observe after another transaction completed reconciliation.
        if query.column_descriptions[0].get("entity") is TransactionLine:
            db_session.execute(
                TransactionLine.__table__.update()
                .where(TransactionLine.id == line.id)
                .values(reconciliation_id=recon.id)
            )
            refreshed.append(True)
        return original(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", simulate_completed_reconciliation)
    with pytest.raises(HTTPException, match="completed reconciliation"):
        assert_not_reconciled(db_session, txn)
    assert refreshed == [True]
    assert line.reconciliation_id == recon.id
    assert db_session.query(Transaction).count() == 1
