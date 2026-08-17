"""link document_audits into a real hash chain + checkpoints

Revision ID: a2b3c4d5e6f9
Revises: e1f2a3b4c5d7
Create Date: 2026-08-18 03:00:00.000000

`document_audits` was a per-document hash ledger: independent SHA-256 rows
with nothing binding row N to row N-1. That detects ALTERATION of a
document's content but not DELETION of an audit row — delete one and every
survivor still verifies perfectly, which is a real hole under
§ 164.312(c)(1) Integrity.

This adds the linkage:

    chain_hash(N) = SHA256(prev_hash | content_hash | doc_type |
                           doc_key | created_at)
    prev_hash(N)  = chain_hash(N-1),  genesis = 64 zeros

and `audit_checkpoints`, which pins (tip id, tip hash, row count) at a
moment in time so truncation of the tail is detectable too — a shortened
chain is still internally valid, so the chain alone cannot catch that.

Existing rows are backfilled deterministically in id order. That
establishes a baseline going forward; it is NOT retroactive proof that
pre-backfill history was untampered, and docs/hipaa-compliance.md says so.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f9"
down_revision: Union[str, None] = "e1f2a3b4c5d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GENESIS_HASH = "0" * 64


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_column("document_audits", "prev_hash"):
        op.add_column(
            "document_audits", sa.Column("prev_hash", sa.String(64), nullable=True)
        )
        op.create_index(
            "ix_document_audits_prev_hash", "document_audits", ["prev_hash"]
        )
    if not _has_column("document_audits", "chain_hash"):
        op.add_column(
            "document_audits", sa.Column("chain_hash", sa.String(64), nullable=True)
        )
        op.create_index(
            "ix_document_audits_chain_hash", "document_audits", ["chain_hash"]
        )

    if "audit_checkpoints" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "audit_checkpoints",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tip_audit_id", sa.Integer(), nullable=False),
            sa.Column("tip_chain_hash", sa.String(64), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("note", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_audit_checkpoints_created_at", "audit_checkpoints", ["created_at"]
        )

    # --- backfill the chain over pre-existing rows ---
    # Deliberately hand-rolled rather than importing the service: a migration
    # must keep working even if the service's hashing is later refactored.
    # Kept byte-identical to services.document_audit.compute_chain_hash.
    import hashlib
    from datetime import timezone

    rows = bind.execute(
        sa.text(
            "SELECT id, doc_type, doc_key, content_hash, created_at, chain_hash "
            "FROM document_audits ORDER BY id"
        )
    ).fetchall()

    prev_hash = GENESIS_HASH
    for row in rows:
        if row.chain_hash:
            prev_hash = row.chain_hash
            continue
        created_at = row.created_at
        if created_at is None:
            stamp = ""
        else:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            stamp = created_at.isoformat()
        material = "|".join(
            [
                prev_hash,
                row.content_hash or "",
                row.doc_type or "",
                row.doc_key or "",
                stamp,
            ]
        )
        chain_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
        bind.execute(
            sa.text(
                "UPDATE document_audits SET prev_hash = :p, chain_hash = :c "
                "WHERE id = :i"
            ),
            {"p": prev_hash, "c": chain_hash, "i": row.id},
        )
        prev_hash = chain_hash


def downgrade() -> None:
    op.drop_table("audit_checkpoints")
    op.drop_index("ix_document_audits_chain_hash", table_name="document_audits")
    op.drop_column("document_audits", "chain_hash")
    op.drop_index("ix_document_audits_prev_hash", table_name="document_audits")
    op.drop_column("document_audits", "prev_hash")
