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

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contractor_pay_runs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("pay_date", sa.Date(), nullable=False),
        sa.Column("memo", sa.String(200), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "processed", "void", name="contractorrunstatus"),
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
            sa.Enum("checking", "savings", name="bankaccountkind"),
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
    op.drop_table("vendor_bank_accounts")
    op.drop_table("contractor_payments")
    op.drop_table("contractor_pay_runs")
