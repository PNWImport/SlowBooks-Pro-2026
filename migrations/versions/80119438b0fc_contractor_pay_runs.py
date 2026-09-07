"""contractor pay runs + vendor bank accounts

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-17 16:00:00.000000

Contractors get the payroll shape — one dated run, many payees, one JE,
one NACHA file — without withholding. ContractorPayment rows join
bill_payments in the 1099-NEC totals; VendorBankAccount is the
direct-deposit destination (encrypted like employee accounts).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "80119438b0fc"
down_revision: Union[str, None] = "aed6d78a0b28"
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
    "contractorrunstatus": ("DRAFT", "PROCESSED", "VOID"),
    "bankaccountkind": ("CHECKING", "SAVINGS"),
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
        "contractor_pay_runs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("pay_date", sa.Date(), nullable=False),
        sa.Column("memo", sa.String(200), nullable=True),
        sa.Column(
            "status",
            _enum_col("contractorrunstatus", is_pg),
            nullable=True,
        ),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "transaction_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_table(
        "contractor_payments",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("contractor_pay_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "vendor_id",
            sa.Integer(),
            sa.ForeignKey("vendors.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
    )
    op.create_table(
        "vendor_bank_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "vendor_id",
            sa.Integer(),
            sa.ForeignKey("vendors.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("nickname", sa.String(100), nullable=True),
        sa.Column(
            "account_kind",
            _enum_col("bankaccountkind", is_pg),
            nullable=True,
        ),
        sa.Column("routing_number_enc", sa.String(255), nullable=True),
        sa.Column("account_number_enc", sa.String(255), nullable=True),
        sa.Column("account_last_four", sa.String(4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    op.drop_table("vendor_bank_accounts")
    op.drop_table("contractor_payments")
    op.drop_table("contractor_pay_runs")
    # Only the types this migration introduced are dropped; shared
    # types (bankaccountkind, payfrequency) belong to earlier migrations.
    if is_pg:
        postgresql.ENUM(name="contractorrunstatus").drop(bind, checkfirst=True)
