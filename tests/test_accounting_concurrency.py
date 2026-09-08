"""Real database coverage for concurrent accounting and audit writes."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.accounts import Account, AccountType
from app.models.transactions import TransactionLine
from app.services.accounting import create_journal_entry


@pytest.fixture(params=["postgresql", "sqlite"])
def accounting_sessions(request, tmp_path):
    if request.param == "sqlite":
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'accounting.db'}")
        try:
            Base.metadata.create_all(engine)
            yield sessionmaker(bind=engine, autoflush=False)
        finally:
            engine.dispose()
        return
    url = os.getenv("MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MIGRATION_TEST_DATABASE_URL is required for concurrent writes")
    schema = "sb_concurrency_" + uuid4().hex
    admin = sa.create_engine(url)
    with admin.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=10000"},
    )
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False)
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("workers, entries_per_worker", [(2, 1), (8, 10)])
def test_concurrent_journals_preserve_all_account_balances(
    accounting_sessions, workers, entries_per_worker
):
    factory = accounting_sessions
    with factory() as db:
        db.add_all(
            [
                Account(id=1, name="Cash", account_type=AccountType.ASSET, balance=0),
                Account(id=2, name="Sales", account_type=AccountType.INCOME, balance=0),
            ]
        )
        db.commit()
    barrier = Barrier(workers)

    def post(reverse):
        with factory() as db:
            # Real request handlers may already have these ORM objects cached.
            cached = db.query(Account).order_by(Account.id).all()
            assert all(a.balance == 0 for a in cached)
            barrier.wait(timeout=10)
            lines = [
                {"account_id": 1, "debit": Decimal("10"), "credit": 0},
                {"account_id": 2, "debit": 0, "credit": Decimal("10")},
            ]
            for _ in range(entries_per_worker):
                create_journal_entry(
                    db,
                    date(2026, 9, 8),
                    "Concurrent sale",
                    lines[::-1] if reverse else lines,
                )
            db.commit()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(post, worker % 2) for worker in range(workers)]
        for future in futures:
            future.result(timeout=30)

    with factory() as db:
        accounts = db.query(Account).order_by(Account.id).all()
        expected = Decimal("10") * workers * entries_per_worker
        assert [a.balance for a in accounts] == [expected, expected]
        lines = db.query(TransactionLine).all()
        assert sum(line.debit for line in lines) == expected
        assert sum(line.credit for line in lines) == expected


@pytest.mark.parametrize("seed_tip", [False, True])
def test_concurrent_document_audits_form_one_chain(accounting_sessions, seed_tip):
    _check_audit_writers(accounting_sessions, seed_tip)


def _check_audit_writers(factory, seed_tip):
    from app.services.document_audit import record_doc_audit, verify_chain

    if seed_tip:
        with factory() as db:
            record_doc_audit(db, "test", "initial", "a" * 64)
    barrier = Barrier(8)

    def append(index):
        with factory() as db:
            db.execute(sa.text("SELECT 1"))
            barrier.wait(timeout=10)
            record_doc_audit(db, "test", str(index), "b" * 64)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(8)))
    with factory() as db:
        report = verify_chain(db)
        assert report["ok"], report
        assert report["rows_verified"] == 8 + int(seed_tip)
