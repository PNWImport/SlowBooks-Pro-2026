"""pay schedules — named pay calendars

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-17 18:00:00.000000

Named pay calendars (frequency + anchor date + submission cutoff +
weekend shifting); employees attach via pay_schedule_id and keep
pay_frequency synced on assignment.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pay_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "frequency",
            sa.Enum(
                "weekly", "biweekly", "semi_monthly", "monthly", name="payfrequency"
            ),
            nullable=False,
        ),
        sa.Column("anchor_pay_date", sa.Date(), nullable=False),
        sa.Column("submission_lead_days", sa.Integer(), nullable=True),
        sa.Column(
            "weekend_shift",
            sa.Enum(
                "none",
                "previous_business_day",
                "next_business_day",
                name="weekendshift",
            ),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.add_column(
        "employees",
        sa.Column(
            "pay_schedule_id",
            sa.Integer(),
            sa.ForeignKey("pay_schedules.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("employees", "pay_schedule_id")
    op.drop_table("pay_schedules")
