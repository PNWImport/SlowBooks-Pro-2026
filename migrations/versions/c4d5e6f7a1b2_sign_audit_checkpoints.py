"""sign audit checkpoints with an operator-held key

Revision ID: c4d5e6f7a1b2
Revises: b3c4d5e6f7a1
Create Date: 2026-08-19 02:00:00.000000

`audit_checkpoints` pinned the chain tip so tail truncation was detectable,
but a checkpoint row lives in the same database an attacker can write. Delete
the audit rows AND the checkpoints and nothing internal notices — the one ❌
in the § 164.312(c)(1) attack table in docs/hipaa-compliance.md.

This adds the signature columns:

    signature            hex HMAC-SHA256 over the canonical checkpoint tuple
    signature_key_id     which operator key signed it
    signature_algorithm  "HMAC-SHA256"

The MAC key lives outside the database (AUDIT_CHECKPOINT_SIGNING_SECRET), so
database write access can delete a checkpoint but cannot mint a replacement
attesting to the truncated state. See app/services/audit_signing.py for what
that does and does not prove.

Existing rows are deliberately NOT back-signed. Signing them now would assert
that the current key attested to those tuples at those times, which nobody can
know — including for a bogus checkpoint an attacker had already inserted. They
stay NULL and verify as `unsigned`, which is reported, not silently accepted.
Take a fresh checkpoint after upgrading.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a1b2"
down_revision: Union[str, None] = "b3c4d5e6f7a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    # Hex HMAC-SHA256 is 64 chars; wider so a longer digest later needs no DDL.
    ("signature", sa.String(128)),
    ("signature_key_id", sa.String(64)),
    ("signature_algorithm", sa.String(32)),
]


def _existing_columns(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    present = _existing_columns("audit_checkpoints")
    if not present:  # table itself missing — a2b3c4d5e6f9 creates it
        return
    for name, type_ in _COLUMNS:
        if name not in present:
            op.add_column("audit_checkpoints", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    present = _existing_columns("audit_checkpoints")
    for name, _type in reversed(_COLUMNS):
        if name in present:
            op.drop_column("audit_checkpoints", name)
