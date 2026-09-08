# ============================================================================
# Migration ⇄ model parity.
# ----------------------------------------------------------------------------
# The rest of the suite builds its schema with Base.metadata.create_all() on
# SQLite, so the Alembic chain is a completely separate, unexercised
# definition of the same database. Two real bugs shipped through that gap:
#
#   1. Enum types declared in migrations with lowercase `.value` labels, when
#      SQLAlchemy persists the UPPERCASE member NAME for a native PostgreSQL
#      enum — plus two type names colliding with earlier migrations, so
#      CREATE TYPE failed outright.
#   2. Four tables and six employee columns that existed only because app
#      startup calls create_all(). create_all backfills a missing TABLE but
#      never adds a column to an existing one, so `alembic upgrade head`
#      produced an employees table six columns short of the model and every
#      ORM insert into it failed.
#
# Both are invisible to a create_all-based suite and fatal on a real
# PostgreSQL deploy. These tests close that gap.
#
# The static tests always run. The full upgrade-and-diff test needs a real
# PostgreSQL and skips without one (set MIGRATION_TEST_DATABASE_URL, or have
# a local postgres reachable as the default bookkeeper DSN).
# ============================================================================

import os
import pathlib
import re
import uuid

import pytest
import sqlalchemy as sa

import app.models  # noqa: F401 — registers every model on the metadata
from app.database import Base

MIGRATIONS_DIR = (
    pathlib.Path(__file__).resolve().parent.parent / "migrations" / "versions"
)

# Structural drift that predates the migration-parity work and is deliberate:
# this column was migrated with a looser type than the model declares.
# Widening/narrowing them is a behavioural change, not a parity fix, so they
# are recorded here rather than silently "corrected".
KNOWN_TYPE_DRIFT = {
    ("inventory_movements", "movement_type"),  # VARCHAR(20) vs Enum(movementtype)
}

# d5e6f7a8b9c0 explicitly preserves these source tables after copying their
# rows into the benefits engine. Their presence protects historical data.
PRESERVED_LEGACY_TABLES = {"deduction_types", "employee_deductions"}


def _migration_files():
    return sorted(p for p in MIGRATIONS_DIR.glob("*.py") if p.name != "__init__.py")


# --- static: enum labels ----------------------------------------------------


def _model_enum_labels() -> dict:
    """{pg type name: (labels...)} for every native enum any model declares."""
    out = {}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            enum_type = getattr(column.type, "enums", None)
            name = getattr(column.type, "name", None)
            if enum_type and name:
                out[name] = tuple(enum_type)
    return out


def test_migration_enum_labels_match_the_models():
    """Every _ENUMS entry must carry the labels SQLAlchemy actually writes.

    This is the exact bug that broke five migrations: labels written as the
    lowercase enum `.value` instead of the uppercase member name.
    """
    expected = _model_enum_labels()
    assert expected, "no native enums found on the model metadata"

    checked = 0
    problems = []
    for path in _migration_files():
        src = path.read_text()
        match = re.search(r"^_ENUMS\s*=\s*\{(.*?)^\}", src, re.S | re.M)
        if not match:
            continue
        for name, body in re.findall(
            r"""["']([a-z_]+)["']\s*:\s*\(([^)]*)\)""", match.group(1)
        ):
            if name not in expected:
                continue
            labels = tuple(lbl for lbl in re.findall(r"""["']([^"']+)["']""", body))
            checked += 1
            if labels != expected[name]:
                problems.append(
                    f"{path.name}: enum {name!r} declares {labels} "
                    f"but the model persists {expected[name]}"
                )
    assert checked, "no migration _ENUMS entries were checked"
    assert (
        not problems
    ), "Enum label mismatch between migrations and models:\n" + "\n".join(problems)


def test_no_migration_declares_a_lowercase_inline_enum():
    """Inline `sa.Enum("draft", ...)` is the bug signature.

    A native enum built from a Python enum class persists member names, so an
    inline declaration with lowercase labels creates a type that rejects every
    value the ORM writes. Migrations must go through the _ENUMS map instead.
    """
    offenders = []
    for path in _migration_files():
        for block in re.findall(r"sa\.Enum\(([^)]*)\)", path.read_text(), re.S):
            labels = re.findall(r"""["']([^"']+)["']""", block)
            # The trailing name="..." kwarg is lowercase by design; skip it.
            value_labels = [
                lbl
                for lbl in labels
                if not re.search(r'name\s*=\s*["\']' + re.escape(lbl), block)
            ]
            bad = [lbl for lbl in value_labels if lbl.islower() and lbl.isidentifier()]
            if bad:
                offenders.append(f"{path.name}: sa.Enum(...) with lowercase {bad}")
    assert not offenders, (
        "Migrations must declare enum labels as UPPERCASE member names via the "
        "_ENUMS idiom:\n" + "\n".join(offenders)
    )


# --- static: every model table is created by some migration -----------------


def test_every_model_table_is_created_by_a_migration():
    """create_all() at startup must not be load-bearing for table creation.

    A table that only create_all() makes has no migration history — bad for
    an auditable deploy, and fatal for any later migration that needs to
    reference it (an FK to document_audits is what first surfaced this).
    """
    created = set()
    for path in _migration_files():
        created |= set(
            re.findall(r"""create_table\(\s*["']([a-z_]+)["']""", path.read_text())
        )
    missing = sorted(set(Base.metadata.tables) - created - {"alembic_version"})
    assert not missing, (
        "Model tables with no create_table in any migration "
        f"(add one, or they exist only via create_all): {missing}"
    )


# --- live: upgrade head and diff against the models -------------------------


def _pg_url():
    url = os.getenv("MIGRATION_TEST_DATABASE_URL") or os.getenv("MIGRATION_TEST_PG_DSN")
    if url:
        return url
    candidate = "postgresql://bookkeeper:bookkeeper@localhost:5432/postgres"
    try:
        sa.create_engine(candidate).connect().close()
        return candidate
    except Exception:
        return None


def _scratch_database_url(admin_url, database):
    # Preserve socket paths, ports, TLS options, and escaped credentials.
    return (
        sa.engine.make_url(admin_url)
        .set(database=database)
        .render_as_string(hide_password=False)
    )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://validation@/postgres?host=/tmp/test-pg&port=57431",
        "postgresql://validation@localhost:57431/postgres?sslmode=verify-full",
        "postgresql://validation:synthetic%2Fpassword@localhost/postgres",
    ],
)
def test_scratch_database_url_preserves_connection_options(url):
    original = sa.engine.make_url(url)
    target = sa.engine.make_url(_scratch_database_url(url, "scratch_test"))
    assert target == original.set(database="scratch_test")


@pytest.mark.skipif(_pg_url() is None, reason="no PostgreSQL available")
@pytest.mark.parametrize("legacy_data", [False, True])
def test_upgrade_head_matches_model_metadata(legacy_data):
    """`alembic upgrade head` on an empty PostgreSQL must reproduce the models.

    Runs the real chain, then asks Alembic to autogenerate a diff against the
    model metadata. Anything structural other than KNOWN_TYPE_DRIFT is a
    parity failure. Index/FK/constraint naming differences between
    hand-written DDL and create_all are expected and ignored.
    """
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext

    admin_url = _pg_url()
    dbname = f"sbparity_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    target = _scratch_database_url(admin_url, dbname)

    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    except sa.exc.ProgrammingError as exc:
        # A read-only or unprivileged role can reach the server but cannot
        # make a scratch database. Skip rather than red — the static parity
        # tests above still run everywhere.
        admin.dispose()
        pytest.skip(f"cannot create a scratch database: {exc.orig}")
    try:
        cfg = Config(str(MIGRATIONS_DIR.parent.parent / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", target.replace("%", "%%"))
        cfg.set_main_option("script_location", str(MIGRATIONS_DIR.parent))
        # migrations/env.py overrides sqlalchemy.url from DATABASE_URL, which
        # the test harness points at its SQLite database — so the env var has
        # to be the one that changes, not just the Config object.
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = target
        try:
            if legacy_data:
                command.upgrade(cfg, "c3d4e5f6a7b8")
                legacy_engine = sa.create_engine(target)
                try:
                    with legacy_engine.begin() as conn:
                        conn.execute(
                            sa.text(
                                "INSERT INTO deduction_types (name, code) "
                                "VALUES ('Legacy retirement deduction', 'LEGACY401K')"
                            )
                        )
                        employee_id = conn.execute(
                            sa.text(
                                "INSERT INTO employees (first_name, last_name) "
                                "VALUES ('Legacy', 'Employee') RETURNING id"
                            )
                        ).scalar_one()
                        conn.execute(
                            sa.text(
                                "INSERT INTO employee_deductions "
                                "(employee_id, deduction_type_id, amount, annual_limit) "
                                "SELECT :employee, id, 125.50, 1500 FROM deduction_types "
                                "WHERE code = 'LEGACY401K'"
                            ),
                            {"employee": employee_id},
                        )
                finally:
                    legacy_engine.dispose()
            command.upgrade(cfg, "head")
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous

        engine = sa.create_engine(target)
        with engine.connect() as conn:
            diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
            if legacy_data:
                election = conn.execute(
                    sa.text(
                        "SELECT employee_rate, annual_cap FROM employee_benefits "
                        "WHERE employee_id = :employee"
                    ),
                    {"employee": employee_id},
                ).one()
                assert str(election.employee_rate) == "125.5000"
                assert str(election.annual_cap) == "1500.00"
                assert (
                    conn.execute(
                        sa.text(
                            "SELECT name FROM benefit_codes WHERE code = 'LEGACY401K'"
                        )
                    ).scalar()
                    == "Legacy retirement deduction"
                )
                assert (
                    conn.execute(
                        sa.text(
                            "SELECT count(*) FROM deduction_types WHERE code = 'LEGACY401K'"
                        )
                    ).scalar()
                    == 1
                )
        engine.dispose()

        structural = []
        for diff in diffs:
            entries = diff if isinstance(diff, list) else [diff]
            for entry in entries:
                kind = entry[0]
                if kind in ("add_index", "remove_index", "add_fk", "remove_fk"):
                    continue
                if kind in ("add_constraint", "remove_constraint"):
                    continue
                if kind in ("add_column", "remove_column"):
                    structural.append(f"{kind}: {entry[2]}.{entry[3].name}")
                elif kind in ("add_table", "remove_table"):
                    if (
                        kind == "remove_table"
                        and entry[1].name in PRESERVED_LEGACY_TABLES
                    ):
                        continue
                    structural.append(f"{kind}: {entry[1].name}")
                elif kind == "modify_type":
                    if (entry[2], entry[3]) in KNOWN_TYPE_DRIFT:
                        continue
                    structural.append(f"modify_type: {entry[2]}.{entry[3]}")
                else:
                    structural.append(str(entry))

        assert not structural, (
            "`alembic upgrade head` does not reproduce the model schema:\n  "
            + "\n  ".join(structural)
        )
    finally:
        with admin.connect() as conn:
            conn.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :d AND pid <> pg_backend_pid()"
                ),
                {"d": dbname},
            )
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}"'))
        admin.dispose()
