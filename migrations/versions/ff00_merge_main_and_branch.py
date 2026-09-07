"""Merge main and feature branch migration chains.

Revision ID: ff00aabb1122
Revises: c4d5e6f7a8b9, e6f7a1b2c3d4
"""

from typing import Sequence, Union

revision: str = "ff00aabb1122"
down_revision: Union[str, Sequence[str]] = ("c4d5e6f7a8b9", "e6f7a1b2c3d4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
