"""Join owner-main settings widening and the payroll branch history.

Revision ID: fa12bc34de56
Revises: d6e7f8a9b0c1, ff00aabb1122

Keep both published histories intact; neither parent revision is renumbered.
"""

revision = "fa12bc34de56"
down_revision = ("d6e7f8a9b0c1", "ff00aabb1122")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
