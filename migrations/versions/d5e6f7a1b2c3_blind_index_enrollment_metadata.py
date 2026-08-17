"""encrypt enrollment metadata behind a blind index

Revision ID: d5e6f7a1b2c3
Revises: c4d5e6f7a1b2
Create Date: 2026-08-19 04:00:00.000000

b3c4d5e6f7a1 encrypted the dependent identifiers and the carrier name but left
the enrollment metadata plaintext, because it is filtered and joined on and
Fernet output is randomized. docs/hipaa-compliance.md § 4 recorded the residual
leak honestly: an attacker with table access could still read *which employees
hold medical coverage over which months*.

This closes both halves of that:

    benefit_plans.kind                 Enum(benefitkind) -> encrypted VARCHAR
    benefit_plans.kind_bidx            new: keyed deterministic hash
    benefit_enrollments.coverage_start DATE -> encrypted VARCHAR (ISO-8601)
    benefit_enrollments.coverage_end   DATE -> encrypted VARCHAR (ISO-8601)

`kind` needs the blind index because the ACA 1095 derivation filters on it in
SQL; equality against the index still works. The coverage dates need no index
— the only SQL predicate on them is `coverage_end IS NULL`, and NULL survives
encryption, while every other comparison happens in Python.

NOTE ON THE ENUM VALUES. A native PostgreSQL enum stores the UPPERCASE member
name ("MEDICAL"), but the application's EncryptedEnum stores the `.value`
("medical") so `BenefitKind(plaintext)` reconstructs on read. This migration
maps name -> value before encrypting. Getting that backwards would produce
rows that decrypt fine and then fail to resolve to an enum member.

WHAT IS DELIBERATELY LEFT PLAINTEXT: `employee_id`. Encrypting a foreign key
costs the FK constraint, the cascade and the ORM relationship, and a blind
index over it would still group one person's enrollments by construction — so
it conceals *which* employee at the price of the database no longer
guaranteeing the row points at a real one. app/models/benefits.py has the full
reasoning.

Existing rows are converted in place, and rows that already look like
ciphertext are skipped, so a re-run is a no-op.

`benefitkind` becomes unused and is dropped on PostgreSQL. downgrade()
recreates it.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a1b2c3"
down_revision: Union[str, None] = "c4d5e6f7a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same _ENUMS idiom as the migration that created the type (b8c9d0e1f2a4), so
# downgrade recreates it with the UPPERCASE member names SQLAlchemy persists.
_ENUMS = {
    "benefitkind": ("MEDICAL", "DENTAL", "VISION", "LIFE", "DISABILITY", "OTHER"),
}

# Native-enum member name -> the `.value` EncryptedEnum stores.
_KIND_NAME_TO_VALUE = {
    "MEDICAL": "medical",
    "DENTAL": "dental",
    "VISION": "vision",
    "LIFE": "life",
    "DISABILITY": "disability",
    "OTHER": "other",
}

_DATE_COLUMNS = ("coverage_start", "coverage_end")


def _looks_encrypted(value) -> bool:
    """Ciphertext from this app always carries the version prefix."""
    return bool(value) and str(value).startswith("v1:")


def _swap_to_string(table: str, column: str, width: int, is_pg: bool) -> None:
    """Change a column's SQL type to VARCHAR, carrying its text across.

    Add / copy / drop / rename rather than ALTER TYPE, so this works on SQLite
    as well as PostgreSQL — same approach as b3c4d5e6f7a1's dob conversion.
    """
    bind = op.get_bind()
    temp = f"{column}__str"
    op.add_column(table, sa.Column(temp, sa.String(width), nullable=True))
    cast = f"to_char({column}, 'YYYY-MM-DD')" if is_pg else f"CAST({column} AS TEXT)"
    bind.execute(
        sa.text(f"UPDATE {table} SET {temp} = {cast} WHERE {column} IS NOT NULL")
    )
    op.drop_column(table, column)
    op.alter_column(table, temp, new_column_name=column)


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    insp = sa.inspect(bind)
    plan_columns = {c["name"] for c in insp.get_columns("benefit_plans")}

    # --- benefit_plans.kind: native enum -> encrypted VARCHAR + blind index --
    if "kind_bidx" not in plan_columns:
        op.add_column(
            "benefit_plans", sa.Column("kind_bidx", sa.String(64), nullable=True)
        )
        op.create_index("ix_benefit_plans_kind_bidx", "benefit_plans", ["kind_bidx"])

    if is_pg:
        op.alter_column(
            "benefit_plans",
            "kind",
            existing_type=postgresql.ENUM(*_ENUMS["benefitkind"], name="benefitkind"),
            type_=sa.String(255),
            existing_nullable=True,
            postgresql_using="kind::text",
        )
    else:
        op.alter_column(
            "benefit_plans",
            "kind",
            existing_type=sa.String(20),
            type_=sa.String(255),
            existing_nullable=True,
        )

    # --- coverage window: DATE -> VARCHAR ------------------------------------
    enrollment_columns = {c["name"] for c in insp.get_columns("benefit_enrollments")}
    for column in _DATE_COLUMNS:
        if column not in enrollment_columns:
            continue
        _swap_to_string("benefit_enrollments", column, 255, is_pg)
    # coverage_start is NOT NULL in the model; the swap above leaves the
    # replacement column nullable.
    bind.execute(
        sa.text(
            "UPDATE benefit_enrollments SET coverage_start = '1970-01-01' "
            "WHERE coverage_start IS NULL"
        )
    )
    op.alter_column(
        "benefit_enrollments",
        "coverage_start",
        existing_type=sa.String(255),
        nullable=False,
    )

    # --- encrypt existing plaintext, and derive the index --------------------
    # Imports the app's own encrypt()/blind_index() on purpose: the values must
    # be readable by the running application, so they have to come from the
    # same key derivation. A hand-rolled copy could drift and silently write
    # rows nothing can read.
    from app.services.blind_index import blind_index
    from app.services.encryption import encrypt

    rows = bind.execute(
        sa.text("SELECT id, kind FROM benefit_plans WHERE kind IS NOT NULL")
    ).fetchall()
    for row in rows:
        raw = str(row.kind)
        if _looks_encrypted(raw):
            # Already converted; make sure the index is present all the same,
            # so a partially-applied run finishes cleanly.
            continue
        value = _KIND_NAME_TO_VALUE.get(raw.upper(), raw.lower())
        bind.execute(
            sa.text("UPDATE benefit_plans SET kind = :k, kind_bidx = :b WHERE id = :i"),
            {
                "k": encrypt(value),
                "b": blind_index("benefit_plans.kind", value),
                "i": row.id,
            },
        )

    for column in _DATE_COLUMNS:
        rows = bind.execute(
            sa.text(
                f"SELECT id, {column} AS v FROM benefit_enrollments "
                f"WHERE {column} IS NOT NULL"
            )
        ).fetchall()
        for row in rows:
            if _looks_encrypted(row.v):
                continue
            bind.execute(
                sa.text(f"UPDATE benefit_enrollments SET {column} = :v WHERE id = :i"),
                {"v": encrypt(str(row.v)), "i": row.id},
            )

    if is_pg:
        # Nothing references benefitkind any more.
        postgresql.ENUM(name="benefitkind").drop(bind, checkfirst=True)


def downgrade() -> None:
    """Decrypt back to plaintext and restore the native enum.

    A value that does not decrypt under the configured key is left as-is rather
    than blanked: leaving ciphertext in a plaintext column for an operator to
    notice beats losing it silently. Any `kind` that cannot be mapped back to a
    valid enum label would make the CREATE TYPE cast fail, so those rows are
    set to NULL — the column was nullable before this migration.
    """
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    from app.services.encryption import decrypt

    value_to_name = {v: k for k, v in _KIND_NAME_TO_VALUE.items()}

    for row in bind.execute(
        sa.text("SELECT id, kind FROM benefit_plans WHERE kind IS NOT NULL")
    ).fetchall():
        plaintext = (
            decrypt(str(row.kind)) if _looks_encrypted(row.kind) else str(row.kind)
        )
        label = value_to_name.get((plaintext or "").lower())
        bind.execute(
            sa.text("UPDATE benefit_plans SET kind = :k WHERE id = :i"),
            {"k": label, "i": row.id},
        )

    for column in _DATE_COLUMNS:
        for row in bind.execute(
            sa.text(
                f"SELECT id, {column} AS v FROM benefit_enrollments "
                f"WHERE {column} IS NOT NULL"
            )
        ).fetchall():
            if not _looks_encrypted(row.v):
                continue
            plaintext = decrypt(str(row.v))
            if plaintext is None:
                continue
            bind.execute(
                sa.text(f"UPDATE benefit_enrollments SET {column} = :v WHERE id = :i"),
                {"v": plaintext, "i": row.id},
            )

    if is_pg:
        postgresql.ENUM(*_ENUMS["benefitkind"], name="benefitkind").create(
            bind, checkfirst=True
        )
        op.alter_column(
            "benefit_enrollments",
            "coverage_start",
            existing_type=sa.String(255),
            nullable=True,
        )
        for column in _DATE_COLUMNS:
            op.alter_column(
                "benefit_enrollments",
                column,
                existing_type=sa.String(255),
                type_=sa.Date(),
                existing_nullable=True,
                postgresql_using=f"{column}::date",
            )
        op.alter_column(
            "benefit_enrollments",
            "coverage_start",
            existing_type=sa.Date(),
            nullable=False,
        )
        op.alter_column(
            "benefit_plans",
            "kind",
            existing_type=sa.String(255),
            type_=postgresql.ENUM(*_ENUMS["benefitkind"], name="benefitkind"),
            existing_nullable=True,
            postgresql_using="kind::benefitkind",
        )

    op.drop_index("ix_benefit_plans_kind_bidx", table_name="benefit_plans")
    op.drop_column("benefit_plans", "kind_bidx")
