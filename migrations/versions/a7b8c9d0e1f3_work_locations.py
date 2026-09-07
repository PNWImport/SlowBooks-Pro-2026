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
    bind = op.get_bind()
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
    # The FOREIGN KEY is declared only on PostgreSQL. Attaching one to an
    # existing table is an ALTER of a constraint, which SQLite has no syntax
    # for — alembic raises NotImplementedError and the chain stops dead on the
    # desktop backend. Batch mode would mean copying the whole employees table
    # to add a nullable column, so this follows the dialect split the rest of
    # these migrations already use. SQLite does not enforce foreign keys
    # unless the pragma is on; the relationship is declared on the ORM model
    # either way, so nothing downstream depends on the constraint existing.
    op.add_column("employees", sa.Column("location_id", sa.Integer(), nullable=True))
    if bind.dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_employees_location_id",
            "employees",
            "work_locations",
            ["location_id"],
            ["id"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_employees_location_id", "employees", type_="foreignkey")
    op.drop_column("employees", "location_id")
    op.drop_table("work_locations")
