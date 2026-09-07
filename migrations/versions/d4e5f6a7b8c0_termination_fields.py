"""employee termination fields

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b8
Create Date: 2026-08-17 20:00:00.000000

termination_date + termination_reason drive the state final-paycheck
deadline and the offboarding flow (services/termination.py).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c0"
down_revision: Union[str, None] = "346a94bbdbd8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("termination_date", sa.Date(), nullable=True))
    op.add_column(
        "employees", sa.Column("termination_reason", sa.String(20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("employees", "termination_reason")
    op.drop_column("employees", "termination_date")
