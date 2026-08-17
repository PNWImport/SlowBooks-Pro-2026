"""garnishment remittance — agency payees + remittance register

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c0
Create Date: 2026-08-17 21:00:00.000000

Withheld garnishment money must be forwarded to an agency. Orders gain
the payee (agency_name/address, remit_reference); each processed pay run
writes GarnishmentRemittance rows the operator marks remitted once the
payment goes out — so withheld-but-never-forwarded money stays visible.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d1"
down_revision: Union[str, None] = "d4e5f6a7b8c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "garnishment_orders", sa.Column("agency_name", sa.String(200), nullable=True)
    )
    op.add_column(
        "garnishment_orders",
        sa.Column("agency_address", sa.String(300), nullable=True),
    )
    op.add_column(
        "garnishment_orders",
        sa.Column("remit_reference", sa.String(80), nullable=True),
    )
    op.create_table(
        "garnishment_remittances",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("garnishment_orders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "pay_run_id",
            sa.Integer(),
            sa.ForeignKey("pay_runs.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("withheld_date", sa.Date(), nullable=False),
        sa.Column("remitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remit_payment_reference", sa.String(120), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("garnishment_remittances")
    op.drop_column("garnishment_orders", "remit_reference")
    op.drop_column("garnishment_orders", "agency_address")
    op.drop_column("garnishment_orders", "agency_name")
