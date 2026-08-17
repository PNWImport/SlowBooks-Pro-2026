"""workers' comp class rates

Revision ID: c9d0e1f2a3b5
Revises: b8c9d0e1f2a4
Create Date: 2026-08-18 00:00:00.000000

Carrier-quoted premium rates per $100 of payroll by (state, class code),
feeding the annual premium-audit report.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b5"
down_revision: Union[str, None] = "b8c9d0e1f2a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wc_class_rates",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("class_code", sa.String(20), nullable=False, index=True),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("rate_per_100", sa.Numeric(10, 4), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("wc_class_rates")
