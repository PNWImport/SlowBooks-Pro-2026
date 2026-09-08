"""Add custom blackout dates to pay schedules.

Revision ID: fb23cd45ef67
Revises: fa12bc34de56
"""

from alembic import op
import sqlalchemy as sa

revision = "fb23cd45ef67"
down_revision = "fa12bc34de56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pay_schedules",
        sa.Column(
            "blackout_dates",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("pay_schedules", "blackout_dates")
