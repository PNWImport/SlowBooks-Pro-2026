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
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a4"
down_revision: Union[str, None] = "a7b8c9d0e1f3"
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
    "benefitkind": ("MEDICAL", "DENTAL", "VISION", "LIFE", "DISABILITY", "OTHER"),
    "enrollmentstatus": ("ACTIVE", "TERMINATED", "COBRA"),
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
        "benefit_plans",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "kind",
            _enum_col("benefitkind", is_pg),
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
            _enum_col("enrollmentstatus", is_pg),
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
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    op.drop_table("benefit_dependents")
    op.drop_table("benefit_enrollments")
    op.drop_table("benefit_plans")
    # Only the types this migration introduced are dropped; shared
    # types (bankaccountkind, payfrequency) belong to earlier migrations.
    if is_pg:
        postgresql.ENUM(name="benefitkind").drop(bind, checkfirst=True)
        postgresql.ENUM(name="enrollmentstatus").drop(bind, checkfirst=True)
