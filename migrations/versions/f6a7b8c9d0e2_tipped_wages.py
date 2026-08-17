"""tipped wages — tip columns on pay stubs

Revision ID: f6a7b8c9d0e2
Revises: e5f6a7b8c9d1
Create Date: 2026-08-17 22:00:00.000000

reported_tips (received directly, taxed but not paid on the check),
paycheck_tips (paid through payroll), tip_credit_topup (employer make-up
to the minimum-wage floor).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e2"
down_revision: Union[str, None] = "e5f6a7b8c9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in ("reported_tips", "paycheck_tips", "tip_credit_topup"):
        op.add_column(
            "pay_stubs",
            sa.Column(column, sa.Numeric(12, 2), nullable=True, server_default="0"),
        )


def downgrade() -> None:
    for column in ("tip_credit_topup", "paycheck_tips", "reported_tips"):
        op.drop_column("pay_stubs", column)
