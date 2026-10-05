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


def test_concurrent_parent_edits_cannot_form_cycle(accounting_sessions):
    from fastapi import HTTPException

    from app.routes.accounts import update_account
    from app.schemas.accounts import AccountUpdate

    factory = accounting_sessions
    with factory() as db:
        db.add_all(
            [
                Account(id=1, name="First", account_type=AccountType.EXPENSE),
                Account(id=2, name="Second", account_type=AccountType.EXPENSE),
            ]
        )
        db.commit()
    barrier = Barrier(2)

    def reparent(account_id, parent_id):
        with factory() as db:
            # Each request has read its account before either acquires locks.
            account = db.get(Account, account_id)
            assert account.parent_id is None
            barrier.wait(timeout=10)
            try:
                update_account(account_id, AccountUpdate(parent_id=parent_id), db)
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
            return 200

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reparent, 1, 2), pool.submit(reparent, 2, 1)]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(results) == [200, 400]
    with factory() as db:
        parents = [row.parent_id for row in db.query(Account).order_by(Account.id)]
        assert parents in ([2, None], [None, 1])


def test_concurrent_migration_imports_do_not_post_twice(
    accounting_sessions, monkeypatch
):
    from threading import BrokenBarrierError
    from app.models.transactions import Transaction
    from app.services import migration_common, wave_import
    from tests.test_wave_import import ACCOUNTING_COA, _accounting_csv

    factory = accounting_sessions
    specs, errors = wave_import.parse_coa(ACCOUNTING_COA)
    assert not errors
    with factory() as db:
        db.add_all([Account(name=a["name"], account_type=a["type"]) for a in specs])
        db.commit()
    original = migration_common.already_imported
    reads = Barrier(2)

    def overlap(db, source):
        found = original(db, source)
        # Force overlapping reads when unprotected. With serialization the
        # first writer times out here and proceeds; the second sees its commit.
        try:
            reads.wait(timeout=1)
        except BrokenBarrierError:
            pass
        return found

    monkeypatch.setattr(migration_common, "already_imported", overlap)
    start = Barrier(2)

    def run():
        with factory() as db:
            start.wait(timeout=10)
            return wave_import.run_import(
                db, {"coa": ACCOUNTING_COA, "gl": _accounting_csv(True)}
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [f.result(timeout=30) for f in futures]
    assert sorted(r["imported_journals"] for r in results) == [0, 2]
    with factory() as db:
        assert db.query(Transaction).filter_by(source_type="wave_import").count() == 2


def test_concurrent_reconciliation_starts_create_only_one_session(
    accounting_sessions, monkeypatch
):
    from threading import BrokenBarrierError
    from fastapi import HTTPException
    from sqlalchemy.orm import Session
    from app.models.banking import Reconciliation
    from app.services import reconciliation

    factory = accounting_sessions
    with factory() as db:
        db.add(
            Account(id=1, name="Bank", account_type=AccountType.ASSET, bank_kind="bank")
        )
        db.commit()
    inserts = Barrier(2)
    original_flush = Session.flush

    def overlap(db, *args, **kwargs):
        if any(isinstance(row, Reconciliation) for row in db.new):
            try:
                inserts.wait(timeout=1)
            except BrokenBarrierError:
                pass
        return original_flush(db, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", overlap)
    start = Barrier(2)

    def open_session():
        with factory() as db:
            start.wait(timeout=10)
            try:
                reconciliation.start(db, 1, date(2026, 9, 20), Decimal("0"))
                db.commit()
                return 201
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: open_session(), range(2)))
    assert sorted(results) == [201, 409]
    with factory() as db:
        assert db.query(Reconciliation).count() == 1
