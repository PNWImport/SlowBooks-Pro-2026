"""A SELECT ... FOR UPDATE returns the row as it is now, and keeps your edits.

Two parallel deposits of one payment both succeeded on PostgreSQL because the
re-read after the lock handed back an object loaded before the wait, stale.
Refreshing every locked read fixes that (app/database.py) — but a route that
changes an object and then locks the next row must not lose the change, which
a credit memo void did until the refresh flushed first.
"""

from sqlalchemy import text

from app.models.accounts import Account, AccountType


def _locked(db, account_id):
    return db.query(Account).filter(Account.id == account_id).with_for_update().first()


def test_a_locked_read_keeps_an_unsaved_change(db_session):
    account = Account(
        name="Lock Keep", account_number="9701", account_type=AccountType.EXPENSE
    )
    db_session.add(account)
    db_session.commit()

    account.name = "Changed, not yet flushed"
    again = _locked(db_session, account.id)
    assert again is account
    assert again.name == "Changed, not yet flushed"
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(Account, account.id).name == "Changed, not yet flushed"


def test_a_locked_read_sees_what_another_transaction_changed(db_session):
    account = Account(
        name="Lock Fresh", account_number="9702", account_type=AccountType.EXPENSE
    )
    db_session.add(account)
    db_session.commit()
    assert account.description is None  # loaded, now cached in the session

    db_session.execute(
        text("UPDATE accounts SET description = 'from elsewhere' WHERE id = :i"),
        {"i": account.id},
    )
    # An ordinary read returns the cached, stale object...
    plain = db_session.query(Account).filter(Account.id == account.id).first()
    assert plain.description is None
    # ...a locked read is the row as it is now.
    assert _locked(db_session, account.id).description == "from elsewhere"
