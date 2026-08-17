"""e-signature envelopes

Revision ID: d0e1f2a3b4c6
Revises: f1a2b3c4d5e8
Create Date: 2026-08-18 00:30:00.000000

Signature envelopes freeze a document body + SHA-256; portal signing
seals (hash, signer, timestamp) into the document_audits chain.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c6"
down_revision: Union[str, None] = "f1a2b3c4d5e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum types this migration touches. Values are the UPPERCASE Python enum
# MEMBER NAMES, because that is what SQLAlchemy persists for a native
# PostgreSQL enum built from an enum class — not the lowercase `.value`.
# Types are created with checkfirst so a name already introduced by an
# earlier migration (bankaccountkind, payfrequency) is reused rather than
# re-created, and referenced with create_type=False so the CREATE is never
# emitted twice. Same idiom as f7a8b9c0d1e2_tier1_payroll_system.py.
_ENUMS = {
    "envelopekind": (
        "OFFER_LETTER",
        "I9_ACKNOWLEDGMENT",
        "HANDBOOK",
        "POLICY",
        "OTHER",
    ),
    "envelopestatus": ("PENDING", "SIGNED", "DECLINED", "VOIDED"),
}


def _enum(name: str):
    return postgresql.ENUM(*_ENUMS[name], name=name, create_type=False)


def _enum_col(name: str, is_pg: bool):
    return _enum(name) if is_pg else sa.Enum(*_ENUMS[name], name=name)


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if is_pg:
        for _name, _values in _ENUMS.items():
            postgresql.ENUM(*_values, name=_name).create(bind, checkfirst=True)

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
            _enum_col("envelopekind", is_pg),
            nullable=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "status",
            _enum_col("envelopestatus", is_pg),
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
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    op.drop_table("signature_envelopes")
    # Only the types this migration introduced are dropped; shared
    # types (bankaccountkind, payfrequency) belong to earlier migrations.
    if is_pg:
        postgresql.ENUM(name="envelopekind").drop(bind, checkfirst=True)
        postgresql.ENUM(name="envelopestatus").drop(bind, checkfirst=True)
