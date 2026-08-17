"""work locations — first-class tax jurisdictions

Revision ID: a7b8c9d0e1f3
Revises: f6a7b8c9d0e2
Create Date: 2026-08-17 23:00:00.000000

WorkLocation pins address + state + locality + default WC class once;
employees attach via location_id and jurisdiction resolution falls back
to the location when explicit per-employee values are unset.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f3"
down_revision: Union[str, None] = "f6a7b8c9d0e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_locations",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("address1", sa.String(200), nullable=True),
        sa.Column("address2", sa.String(200), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("zip", sa.String(20), nullable=True),
        sa.Column("locality", sa.String(40), nullable=True),
        sa.Column("default_wc_class_code", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.add_column(
        "employees",
        sa.Column(
            "location_id",
            sa.Integer(),
            sa.ForeignKey("work_locations.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("employees", "location_id")
    op.drop_table("work_locations")
