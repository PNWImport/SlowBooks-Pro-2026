"""merge the branch, upstream and ACH migration heads

Revision ID: m3heads2026105
Revises: e2b7c4d9a1f3
Create Date: 2026-10-05 11:33:37.921394

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "m3heads2026105"
down_revision: Union[str, Sequence[str], None] = (
    "ab12cd34ef56",
    "c7d1e4a92b30",
    "e2b7c4d9a1f3",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
