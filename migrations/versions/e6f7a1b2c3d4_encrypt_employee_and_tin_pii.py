"""Encrypt employee PII, taxpayer IDs, and garnishment agency addresses.

The benefits ePHI was encrypted in b3c4d5e6f7a1, but the identifiers that
make it re-identifiable were left in plaintext: an employee's SSN last-4
and home address sit one join away from an encrypted enrollment. HIPAA
treats those identifiers as part of the protected set, so leaving them
readable weakened the encryption that was already there.

Also covered here:
  customers.tax_id / vendors.tax_id  taxpayer IDs on the 1099 path
  garnishment_orders.agency_address  identifies an order's nature (child
                                     support, tax levy) by its recipient

Deliberately NOT encrypted:
  employees.email          an operational routing key; the same address is
                           already stored plaintext in email_log.recipient,
                           so encrypting one copy buys nothing
  benefit_enrollments.employee_id  a foreign key. Encrypting a join key
                           breaks the FK constraint, the ORM relationship
                           and cascade deletes. The consequence is honest
                           and documented: coverage DETAILS are protected,
                           the FACT of an enrollment is not.

Every target column was checked to be free of filters, indexes and unique
constraints before encrypting — randomized ciphertext would silently break
any of those.

Revision ID: e6f7a1b2c3d4
Revises: d5e6f7a1b2c3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a1b2c3d4"
down_revision: Union[str, None] = "d5e6f7a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, old width, new width)
_TARGETS = [
    ("employees", "ssn_last_four", 4, 255),
    ("employees", "address1", 200, 500),
    ("employees", "address2", 200, 500),
    ("customers", "tax_id", 50, 255),
    ("vendors", "tax_id", 50, 255),
    ("garnishment_orders", "agency_address", 300, 500),
]


def _looks_encrypted(value: str) -> bool:
    """Fernet tokens start with 'gAAAAA'. Lets the migration re-run without
    double-encrypting anything it already converted."""
    return value.startswith("gAAAAA")


def upgrade() -> None:
    bind = op.get_bind()

    # Widen first — ciphertext is far longer than the plaintext it replaces,
    # and ssn_last_four at String(4) cannot hold a token at all.
    #
    # PostgreSQL only: ALTER COLUMN ... TYPE is not SQLite syntax, and issuing
    # it unconditionally raised "near ALTER: syntax error", stopping the whole
    # migration chain on the desktop backend. SQLite does not enforce a
    # declared VARCHAR width — the value is stored as TEXT regardless — so the
    # columns there already hold the ciphertext without being widened.
    if bind.dialect.name == "postgresql":
        for table, column, old, new in _TARGETS:
            op.alter_column(
                table,
                column,
                existing_type=sa.String(old),
                type_=sa.String(new),
                existing_nullable=True,
            )

    # Encrypt in place using the application's own encrypt(), so the
    # ciphertext is readable by the running app. A migration that hand-rolled
    # the key derivation could drift and write values nothing can read.
    from app.services.encryption import encrypt

    for table, column, _old, _new in _TARGETS:
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
    """Decrypt back to plaintext and narrow the columns.

    A value that does not decrypt under the configured key is left as-is
    rather than blanked: leaving ciphertext in a plaintext column for an
    operator to notice beats silently destroying the row. Narrowing is
    skipped for any column still holding something too long, so the
    downgrade cannot truncate data.
    """
    bind = op.get_bind()
    from app.services.encryption import decrypt

    for table, column, old, new in _TARGETS:
        rows = bind.execute(
            sa.text(f"SELECT id, {column} AS v FROM {table} WHERE {column} IS NOT NULL")
        ).fetchall()
        for row in rows:
            value = row.v
            if value is None or value == "" or not _looks_encrypted(str(value)):
                continue
            try:
                plain = decrypt(str(value))
            except Exception:
                continue
            bind.execute(
                sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :i"),
                {"v": plain, "i": row.id},
            )

        too_long = bind.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE {column} IS NOT NULL AND LENGTH({column}) > {old}"
            )
        ).scalar()
        if too_long:
            continue
        # PostgreSQL only, mirroring the widening in upgrade().
        if bind.dialect.name == "postgresql":
            op.alter_column(
                table,
                column,
                existing_type=sa.String(new),
                type_=sa.String(old),
                existing_nullable=True,
            )
