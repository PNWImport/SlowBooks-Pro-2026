"""Per-user bank-details access flag.

Revision ID: ab12cd34ef56
Revises: ff00aabb1122
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ab12cd34ef56"
down_revision: Union[str, Sequence[str], None] = "ff00aabb1122"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "can_access_bank_details",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("can_access_bank_details")
