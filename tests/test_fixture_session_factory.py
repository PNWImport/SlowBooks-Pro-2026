"""The reusable factory keeps isolated databases and exactly one audit hook."""

import pytest

import app.database as database
from app.models.accounts import Account, AccountType
from app.models.audit import AuditLog

_seen_factories = []


@pytest.mark.parametrize("iteration", range(3))
def test_factory_reused_without_rows_or_duplicate_hooks(
    TestSession, db_session, iteration
):
    assert TestSession is database.SessionLocal
    if _seen_factories:
        assert TestSession is _seen_factories[0]
    _seen_factories.append(TestSession)
    assert db_session.query(Account).count() == 0
    assert db_session.query(AuditLog).count() == 0
    account = Account(name=f"Isolated {iteration}", account_type=AccountType.ASSET)
    db_session.add(account)
    db_session.commit()
    assert db_session.query(Account).count() == 1
    assert db_session.query(AuditLog).count() == 1
