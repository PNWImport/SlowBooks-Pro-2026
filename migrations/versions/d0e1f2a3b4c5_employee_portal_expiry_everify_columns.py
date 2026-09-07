"""add employee portal-expiry and e-verify lifecycle columns

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-05 12:00:00.000000

The Employee model declares portal_token_last_used / portal_token_expires_at
(token idle + hard expiry windows) and the E-Verify lifecycle columns
(everify_status / everify_submitted_at / everify_closed_at / everify_notes),
but the tier3 migration only created portal_token and everify_case_number.
On a properly-migrated database (create_all only creates missing tables —
it never ALTERs the existing employees table) every employee create, portal
access, and E-Verify update crashed with UndefinedColumn.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The same six columns are added by f1a2b3c4d5e8 on the other line of
# development this branch merged with. Both revisions are now in the chain,
# so whichever runs second must be a no-op rather than a duplicate-column
# error — hence the existence check on every add and drop.
_COLUMNS = (
    ("portal_token_last_used", sa.DateTime(timezone=True)),
    ("portal_token_expires_at", sa.DateTime(timezone=True)),
    ("everify_status", sa.String(30)),
    ("everify_submitted_at", sa.DateTime(timezone=True)),
    ("everify_closed_at", sa.DateTime(timezone=True)),
    ("everify_notes", sa.Text()),
)


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    for column, coltype in _COLUMNS:
        if not _has_column("employees", column):
            op.add_column("employees", sa.Column(column, coltype, nullable=True))


def downgrade() -> None:
    for column, _ in reversed(_COLUMNS):
        if _has_column("employees", column):
            op.drop_column("employees", column)
