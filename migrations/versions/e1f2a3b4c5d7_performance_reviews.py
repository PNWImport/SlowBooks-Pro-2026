"""performance reviews

Revision ID: e1f2a3b4c5d7
Revises: d0e1f2a3b4c6
Create Date: 2026-08-18 01:00:00.000000

draft -> submitted -> acknowledged review records with rating, goals,
feedback, and an employee comment on acknowledgment.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d7"
down_revision: Union[str, None] = "d0e1f2a3b4c6"
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
    "reviewstatus": ("DRAFT", "SUBMITTED", "ACKNOWLEDGED"),
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
        "performance_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "reviewer_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "status",
            _enum_col("reviewstatus", is_pg),
            nullable=True,
        ),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("goals", sa.Text(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("employee_comment", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    op.drop_table("performance_reviews")
    # Only the types this migration introduced are dropped; shared
    # types (bankaccountkind, payfrequency) belong to earlier migrations.
    if is_pg:
        postgresql.ENUM(name="reviewstatus").drop(bind, checkfirst=True)
