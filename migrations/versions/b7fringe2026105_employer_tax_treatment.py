"""Add explicit employer fringe tax treatment without reclassifying history.

Revision ID: b7fringe2026105
Revises: m3heads2026105
"""

from alembic import op
import sqlalchemy as sa

revision = "b7fringe2026105"
down_revision = "m3heads2026105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL preserves legacy uncertainty, including seeded group-term life.
    # Historical PayStubBenefit.rule_json remains completely unchanged.
    op.add_column(
        "benefit_codes",
        sa.Column("employer_tax_treatment", sa.String(24), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("benefit_codes") as batch:
        batch.drop_column("employer_tax_treatment")
