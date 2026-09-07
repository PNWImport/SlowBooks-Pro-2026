"""encrypt the benefits ePHI surface at rest

Revision ID: b3c4d5e6f7a1
Revises: a2b3c4d5e6f9
Create Date: 2026-08-18 04:00:00.000000

Health-plan enrollment tied to a named individual is individually
identifiable information relating to payment for healthcare. The benefits
module stored the identifying parts in plaintext, which docs/hipaa-compliance.md
flagged High. These columns now hold Fernet ciphertext under the same key as
employee bank PII:

    benefit_plans.carrier_name
    benefit_dependents.name
    benefit_dependents.ssn_last_four
    benefit_dependents.dob          (Date -> ISO string, then encrypted)

Columns are widened first (ciphertext is ~100-200 chars for short input),
then existing plaintext rows are encrypted in place. Rows that already look
like ciphertext are skipped, so a re-run is a no-op.

DOB changes SQL type from DATE to VARCHAR. That is not reversible without
data loss for any value written after this migration, so downgrade()
decrypts back to a date where it can and drops values it cannot parse — see
the comment there before relying on it.

Deliberately still plaintext: plan name/kind, coverage dates, premium
amounts, employee_id. Those are filtered, sorted and joined on (the ACA
month-of-coverage derivation needs plan kind and coverage windows), and
Fernet output is randomized. Encrypting them requires a blind index —
tracked in docs/todo.md.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a1"
down_revision: Union[str, None] = "a2b3c4d5e6f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, new width)
_WIDEN = [
    ("benefit_plans", "carrier_name", 500),
    ("benefit_dependents", "name", 500),
    ("benefit_dependents", "ssn_last_four", 255),
]


def _looks_encrypted(value: str) -> bool:
    """Fernet ciphertext from this app always carries the version prefix."""
    return bool(value) and value.startswith("v1:")


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # --- widen the string columns so ciphertext fits ---
    # PostgreSQL only. ALTER COLUMN ... TYPE is not SQLite syntax, so this
    # raised "near ALTER: syntax error" and stopped the chain on the desktop
    # backend. Nothing is lost by skipping it: SQLite has no VARCHAR(n)
    # enforcement — a declared width is advisory and the value is stored as
    # TEXT whatever it says — so the ciphertext already fits there.
    if is_pg:
        for table, column, width in _WIDEN:
            nullable = not (table == "benefit_dependents" and column == "name")
            op.alter_column(
                table,
                column,
                existing_type=sa.String(200 if column == "name" else 120),
                type_=sa.String(width),
                existing_nullable=nullable,
            )

    # --- dob: DATE -> VARCHAR, carrying the ISO text across ---
    op.add_column(
        "benefit_dependents", sa.Column("dob_enc", sa.String(255), nullable=True)
    )
    bind.execute(
        sa.text(
            "UPDATE benefit_dependents SET dob_enc = "
            + ("to_char(dob, 'YYYY-MM-DD')" if is_pg else "CAST(dob AS TEXT)")
            + " WHERE dob IS NOT NULL"
        )
    )
    op.drop_column("benefit_dependents", "dob")
    op.alter_column("benefit_dependents", "dob_enc", new_column_name="dob")

    # --- encrypt existing plaintext in place ---
    # Imports the app's encrypt() on purpose: the ciphertext must be readable
    # by the running application, so it has to be produced by the same key
    # derivation. A migration that hand-rolled this could drift from the app
    # and silently write values nothing can read.
    from app.services.encryption import encrypt

    for table, column in [
        ("benefit_plans", "carrier_name"),
        ("benefit_dependents", "name"),
        ("benefit_dependents", "ssn_last_four"),
        ("benefit_dependents", "dob"),
    ]:
        rows = bind.execute(
            sa.text(f"SELECT id, {column} AS v FROM {table} WHERE {column} IS NOT NULL")
        ).fetchall()
        for row in rows:
            value = row.v
            if value is None or value == "" or _looks_encrypted(str(value)):
                continue
            bind.execute(
                sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :i"),
                {"v": encrypt(str(value)), "i": row.id},
            )


def downgrade() -> None:
    """Decrypt back to plaintext.

    Any value that does not decrypt under the configured key is left as-is
    rather than blanked — losing it silently would be worse than leaving
    ciphertext in a plaintext column for an operator to notice. The dob
    column comes back as DATE and drops anything unparseable.
    """
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    from app.services.encryption import decrypt

    for table, column in [
        ("benefit_plans", "carrier_name"),
        ("benefit_dependents", "name"),
        ("benefit_dependents", "ssn_last_four"),
        ("benefit_dependents", "dob"),
    ]:
        rows = bind.execute(
            sa.text(f"SELECT id, {column} AS v FROM {table} WHERE {column} IS NOT NULL")
        ).fetchall()
        for row in rows:
            if not _looks_encrypted(str(row.v)):
                continue
            plaintext = decrypt(str(row.v))
            if plaintext is None:
                continue
            bind.execute(
                sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :i"),
                {"v": plaintext, "i": row.id},
            )

    op.add_column("benefit_dependents", sa.Column("dob_date", sa.Date(), nullable=True))
    bind.execute(
        sa.text(
            "UPDATE benefit_dependents SET dob_date = CAST(dob AS DATE) "
            "WHERE dob IS NOT NULL AND dob ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'"
            if bind.dialect.name == "postgresql"
            else "UPDATE benefit_dependents SET dob_date = dob "
            "WHERE dob IS NOT NULL AND length(dob) = 10"
        )
    )
    op.drop_column("benefit_dependents", "dob")
    op.alter_column("benefit_dependents", "dob_date", new_column_name="dob")

    # PostgreSQL only, mirroring the widening in upgrade().
    if is_pg:
        for table, column, width in _WIDEN:
            nullable = not (table == "benefit_dependents" and column == "name")
            op.alter_column(
                table,
                column,
                existing_type=sa.String(width),
                type_=sa.String(200 if column == "name" else 120),
                existing_nullable=nullable,
            )
