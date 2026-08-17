"""benefits — plans, enrollments, dependents

Revision ID: b8c9d0e1f2a4
Revises: a7b8c9d0e1f3
Create Date: 2026-08-17 23:30:00.000000

Record-keeping half of benefits admin: plans, per-employee enrollments
with coverage windows, dependents. Feeds ACA 1095/1094 derivation and
COBRA election notices. No carrier feeds by design.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a4"
down_revision: Union[str, None] = "a7b8c9d0e1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "benefit_plans",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "kind",
            sa.Enum(
                "medical",
                "dental",
                "vision",
                "life",
                "disability",
                "other",
                name="benefitkind",
            ),
            nullable=True,
        ),
        sa.Column("carrier_name", sa.String(120), nullable=True),
        sa.Column("self_insured", sa.Boolean(), nullable=True),
        sa.Column("provides_mec", sa.Boolean(), nullable=True),
        sa.Column("monthly_premium_employee", sa.Numeric(12, 2), nullable=True),
        sa.Column("monthly_premium_employer", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_table(
        "benefit_enrollments",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "plan_id", sa.Integer(), sa.ForeignKey("benefit_plans.id"), nullable=False
        ),
        sa.Column("coverage_start", sa.Date(), nullable=False),
        sa.Column("coverage_end", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "terminated", "cobra", name="enrollmentstatus"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_table(
        "benefit_dependents",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "enrollment_id",
            sa.Integer(),
            sa.ForeignKey("benefit_enrollments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("relationship_kind", sa.String(30), nullable=True),
        sa.Column("ssn_last_four", sa.String(4), nullable=True),
        sa.Column("dob", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("benefit_dependents")
    op.drop_table("benefit_enrollments")
    op.drop_table("benefit_plans")
