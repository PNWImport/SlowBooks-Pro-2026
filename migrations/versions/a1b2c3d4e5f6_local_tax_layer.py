"""local tax layer — employee localities + pay-stub local tax columns

Revision ID: a1b2c3d4e5f6
Revises: c9d0e1f2a3b4
Create Date: 2026-08-17 12:00:00.000000

Municipal / county / school-district payroll taxes (PA EIT + LST, OH
municipal + SD, NYC/Yonkers, MD + IN counties, KY occupational, MI
cities). Employees carry a work and residence locality code resolving
into app/services/local_tax/localities/; each stub records the locality
it was taxed under plus the employee- and employer-side local tax.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("work_locality", sa.String(40), nullable=True))
    op.add_column(
        "employees", sa.Column("residence_locality", sa.String(40), nullable=True)
    )
    op.add_column("pay_stubs", sa.Column("work_locality", sa.String(40), nullable=True))
    op.add_column(
        "pay_stubs",
        sa.Column("local_tax", sa.Numeric(12, 2), nullable=True, server_default="0"),
    )
    op.add_column(
        "pay_stubs",
        sa.Column(
            "local_tax_employer", sa.Numeric(12, 2), nullable=True, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("pay_stubs", "local_tax_employer")
    op.drop_column("pay_stubs", "local_tax")
    op.drop_column("pay_stubs", "work_locality")
    op.drop_column("employees", "residence_locality")
    op.drop_column("employees", "work_locality")
