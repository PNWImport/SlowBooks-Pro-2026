"""Join local payroll hardening and the upstream banking schema.

No data changes: each parent retains its own published migration history.
"""

revision = "ac14bd25ce36"
down_revision = ("fb23cd45ef67", "f8a9b0c1d2e3")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
