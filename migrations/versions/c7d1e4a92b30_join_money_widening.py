"""Join local payroll/banking history with the upstream money widening.

Upstream a9b0c1d2e3f4 widens every Numeric(12, 2) column it finds in the
live schema, but it is a sibling of this branch's local join
(ac14bd25ce36), so on a fresh database the local payroll lineage can run
after it and create Numeric(12, 2) columns that the widening never saw.
This revision repeats the same live-schema discovery once both parents have
run, so every money column ends at Numeric(15, 2) regardless of order. It is
a no-op when nothing is left at precision 12.

Downgrade does nothing: a9b0c1d2e3f4's downgrade narrows all Numeric(15, 2)
columns back, including the ones widened here.

Revision ID: c7d1e4a92b30
Revises: ac14bd25ce36, a9b0c1d2e3f4
Create Date: 2026-09-26

"""

from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c7d1e4a92b30"
down_revision: Union[str, Sequence[str], None] = ("ac14bd25ce36", "a9b0c1d2e3f4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _money_columns_at_12() -> list[tuple[str, str]]:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        rows = bind.execute(sa.text("""
                SELECT c.table_name, c.column_name
                FROM information_schema.columns c
                JOIN information_schema.tables t
                  ON t.table_schema = c.table_schema
                 AND t.table_name = c.table_name
                WHERE c.table_schema = current_schema()
                  AND t.table_type = 'BASE TABLE'
                  AND c.data_type = 'numeric'
                  AND c.numeric_precision = 12
                  AND c.numeric_scale = 2
                ORDER BY c.table_name, c.column_name
                """)).fetchall()
        return [(row[0], row[1]) for row in rows]

    insp = sa.inspect(bind)
    found = []
    for table in insp.get_table_names():
        for col in insp.get_columns(table):
            typ = col["type"]
            if (
                getattr(typ, "precision", None) == 12
                and getattr(typ, "scale", None) == 2
            ):
                found.append((table, col["name"]))
    found.sort()
    return found


def upgrade() -> None:
    by_table: dict[str, list[str]] = defaultdict(list)
    for table, column in _money_columns_at_12():
        by_table[table].append(column)
    for table in sorted(by_table):
        with op.batch_alter_table(table) as batch:
            for column in by_table[table]:
                batch.alter_column(
                    column,
                    existing_type=sa.Numeric(12, 2),
                    type_=sa.Numeric(15, 2),
                )


def downgrade() -> None:
    pass
