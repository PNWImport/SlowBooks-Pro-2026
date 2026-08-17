"""e-signature envelopes

Revision ID: d0e1f2a3b4c6
Revises: c9d0e1f2a3b5
Create Date: 2026-08-18 00:30:00.000000

Signature envelopes freeze a document body + SHA-256; portal signing
seals (hash, signer, timestamp) into the document_audits chain.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c6"
down_revision: Union[str, None] = "c9d0e1f2a3b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signature_envelopes",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "kind",
            sa.Enum(
                "offer_letter",
                "i9_acknowledgment",
                "handbook",
                "policy",
                "other",
                name="envelopekind",
            ),
            nullable=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "signed", "declined", "voided", name="envelopestatus"),
            nullable=True,
        ),
        sa.Column("signer_name", sa.String(200), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "signature_audit_id",
            sa.Integer(),
            sa.ForeignKey("document_audits.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("signature_envelopes")
