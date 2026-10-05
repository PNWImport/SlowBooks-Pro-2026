"""Repair must prove ownership and dependency safety before dropping tables."""

import pytest
from sqlalchemy import create_engine, inspect, text

from app.services import schema_repair as repair


@pytest.fixture
def repair_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'repair.db'}")
    try:
        yield engine
    finally:
        engine.dispose()


def test_retry_preserves_empty_table_not_created_by_pending_migrations(
    repair_db, monkeypatch
):
    from alembic import command

    with repair_db.begin() as conn:
        conn.execute(text("CREATE TABLE operator_owned (id INTEGER PRIMARY KEY)"))
    monkeypatch.setattr(
        repair, "tables_pending_revisions_would_create", lambda *a: set()
    )

    def fail_upgrade(*args):
        raise RuntimeError("table operator_owned already exists")

    monkeypatch.setattr(command, "upgrade", fail_upgrade)
    result = repair.repair(str(repair_db.url))
    assert not result.ok
    assert result.dropped == []
    assert inspect(repair_db).has_table("operator_owned")
    assert "not created by a pending migration" in result.message


@pytest.mark.parametrize(
    "shape", ["external_child", "cycle", "populated_child", "diamond"]
)
def test_blocker_dependency_safety(repair_db, shape):
    with repair_db.begin() as conn:
        conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
            )
        )
        if shape == "cycle":
            conn.execute(
                text(
                    "ALTER TABLE parent ADD COLUMN child_id INTEGER REFERENCES child(id)"
                )
            )
        if shape == "populated_child":
            conn.execute(text("INSERT INTO child (id) VALUES (1)"))
        if shape == "diamond":
            conn.execute(
                text(
                    "CREATE TABLE sibling (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE leaf (id INTEGER PRIMARY KEY, child_id INTEGER REFERENCES child(id), sibling_id INTEGER REFERENCES sibling(id))"
                )
            )
    pending = (
        {"parent"}
        if shape == "external_child"
        else {"parent", "child", "sibling", "leaf"}
    )
    order, refusal = repair._empty_blocker_drop_order(repair_db, "parent", pending)
    if shape == "diamond":
        assert refusal is None
        assert len(order) == len(set(order)) == 4
        assert order.index("leaf") < order.index("child") < order.index("parent")
        assert order.index("leaf") < order.index("sibling") < order.index("parent")
    else:
        assert order == []
        expected = {
            "external_child": "not created",
            "cycle": "cycle",
            "populated_child": "holds 1 row(s)",
        }
        assert expected[shape] in refusal
    assert inspect(repair_db).has_table("parent")
    assert inspect(repair_db).has_table("child")


@pytest.mark.parametrize("error", ["connection refused", "table absent already exists"])
def test_unrecoverable_upgrade_does_not_guess(repair_db, monkeypatch, error):
    from alembic import command

    def fail_upgrade(*args):
        raise RuntimeError(error)

    monkeypatch.setattr(command, "upgrade", fail_upgrade)
    result = repair.repair(str(repair_db.url))
    assert not result.ok
    assert result.dropped == []
    assert (
        "another reason" if error == "connection refused" else "not guessing"
    ) in result.message


def test_dry_run_does_not_call_upgrade_or_modify_database(repair_db, monkeypatch):
    from alembic import command

    with repair_db.begin() as conn:
        conn.execute(text("CREATE TABLE keep (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO keep VALUES (7)"))

    def unexpected_upgrade(*args):
        pytest.fail("dry run called migrations")

    monkeypatch.setattr(command, "upgrade", unexpected_upgrade)
    result = repair.repair(str(repair_db.url), dry_run=True)
    assert result.ok and result.dropped == []
    assert "dry run" in result.message
    with repair_db.connect() as conn:
        assert conn.execute(text("SELECT id FROM keep")).all() == [(7,)]


def test_retry_budget_is_bounded_when_upgrade_recreates_blocker(repair_db, monkeypatch):
    from alembic import command

    calls = []

    def fail_upgrade(*args):
        calls.append(True)
        with repair_db.begin() as conn:
            conn.execute(text("CREATE TABLE pending (id INTEGER PRIMARY KEY)"))
        raise RuntimeError("table pending already exists")

    monkeypatch.setattr(command, "upgrade", fail_upgrade)
    monkeypatch.setattr(repair, "MAX_ROUNDS", 2)
    monkeypatch.setattr(
        repair, "tables_pending_revisions_would_create", lambda *a: {"pending"}
    )
    result = repair.repair(str(repair_db.url))
    assert not result.ok
    assert len(calls) == 2
    assert result.dropped == ["pending"]
    assert "gave up after 2 rounds" in result.message


def test_half_upgrade_advice_fails_closed_on_inspection_error(repair_db, monkeypatch):
    def unavailable(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(repair, "_current_revision", unavailable)
    assert repair.looks_half_upgraded(repair_db) is False


def test_preclear_inspection_failure_uses_upgrade_without_dropping_data(
    repair_db, monkeypatch, caplog
):
    from alembic import command

    with repair_db.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('old')"))
        conn.execute(text("CREATE TABLE keep (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO keep VALUES (7)"))
    calls = []

    def unavailable(*args):
        raise OSError("migration source unavailable")

    def upgrade(config, target):
        calls.append(target)
        with repair_db.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = 'new'"))

    monkeypatch.setattr(repair, "_blocking_created_tables", unavailable)
    monkeypatch.setattr(command, "upgrade", upgrade)
    result = repair.repair(str(repair_db.url))
    assert result.ok and result.now_at == "new"
    assert result.dropped == [] and calls == ["head"]
    assert "could not pre-clear" in caplog.text
    with repair_db.connect() as conn:
        assert conn.execute(text("SELECT id FROM keep")).all() == [(7,)]


@pytest.mark.parametrize("stamped", [False, True])
def test_half_upgrade_advice_is_false_for_unstamped_or_current_database(
    repair_db, stamped
):
    from alembic.script import ScriptDirectory

    if stamped:
        head = ScriptDirectory.from_config(
            repair._alembic_cfg(str(repair_db.url))
        ).get_current_head()
        with repair_db.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
            conn.execute(
                text("INSERT INTO alembic_version VALUES (:head)"), {"head": head}
            )
    assert repair.looks_half_upgraded(repair_db) is False


def test_pending_table_discovery_skips_current_and_warns_on_unreadable_script(
    tmp_path, monkeypatch, caplog
):
    from types import SimpleNamespace
    from alembic.script import ScriptDirectory

    current = tmp_path / "current.py"
    current.write_text('op.create_table("existing")')
    next_revision = tmp_path / "next.py"
    next_revision.write_text('op.create_table("pending")')
    missing = tmp_path / "missing.py"
    revisions = [
        SimpleNamespace(revision="current", path=str(current)),
        SimpleNamespace(revision="next", path=str(next_revision)),
        SimpleNamespace(revision="missing", path=str(missing)),
    ]

    def iterate(head, base, *, implicit_base):
        assert (head, base, implicit_base) == ("next", "current", True)
        return revisions

    script = SimpleNamespace(get_current_head=lambda: "next", iterate_revisions=iterate)
    monkeypatch.setattr(ScriptDirectory, "from_config", lambda config: script)
    assert repair.tables_pending_revisions_would_create("sqlite://", "current") == {
        "pending"
    }
    assert "could not read migration" in caplog.text
