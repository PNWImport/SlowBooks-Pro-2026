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
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "346a94bbdbd8"
down_revision: Union[str, None] = "80119438b0fc"
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
    "payfrequency": ("WEEKLY", "BIWEEKLY", "SEMI_MONTHLY", "MONTHLY"),
    "weekendshift": ("NONE", "PREVIOUS_BUSINESS_DAY", "NEXT_BUSINESS_DAY"),
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
        "pay_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "frequency",
            _enum_col("payfrequency", is_pg),
            nullable=False,
        ),
        sa.Column("anchor_pay_date", sa.Date(), nullable=False),
        sa.Column("submission_lead_days", sa.Integer(), nullable=True),
        sa.Column(
            "weekend_shift",
            _enum_col("weekendshift", is_pg),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    # The FOREIGN KEY is declared only on PostgreSQL. Attaching one to an
    # existing table is an ALTER of a constraint, which SQLite has no syntax
    # for — alembic raises NotImplementedError and the chain stops dead on the
    # desktop backend. Batch mode would mean copying the whole employees table
    # to add a nullable column, so this follows the dialect split the rest of
    # these migrations already use. SQLite does not enforce foreign keys
    # unless the pragma is on; the relationship is declared on the ORM model
    # either way, so nothing downstream depends on the constraint existing.
    op.add_column(
        "employees", sa.Column("pay_schedule_id", sa.Integer(), nullable=True)
    )
    if bind.dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_employees_pay_schedule_id",
            "employees",
            "pay_schedules",
            ["pay_schedule_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "fk_employees_pay_schedule_id", "employees", type_="foreignkey"
        )
    op.drop_column("employees", "pay_schedule_id")
    op.drop_table("pay_schedules")
    # Only the types this migration introduced are dropped; shared
    # types (bankaccountkind, payfrequency) belong to earlier migrations.
    if is_pg:
        postgresql.ENUM(name="weekendshift").drop(bind, checkfirst=True)
