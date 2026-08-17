"""backfill orphaned audit tables + employee columns

Revision ID: f1a2b3c4d5e8
Revises: c9d0e1f2a3b5
Create Date: 2026-08-18 02:00:00.000000

Two classes of schema that the migration chain never carried.

FOUR TABLES introduced as models only, existing purely because app
startup calls Base.metadata.create_all():

    document_audits    tamper-evident hashes for generated tax forms
    login_attempts     admin login success/failure trail
    portal_accesses    employee-portal access log
    reseller_permits   permit expiry + verification trail

That split schema provenance across two mechanisms. It mattered for two
reasons. First, three of those tables are the ones docs/hipaa-compliance.md
cites as the § 164.312(b) audit controls, and a compliance story should
not rest on a table whose creation is not in the migration history.
Second, migrations run BEFORE create_all in the documented deploy path
(docker-entrypoint.sh: alembic upgrade head, then boot), so the following
migration's FK from signature_envelopes.signature_audit_id to
document_audits had no target and failed outright.

SIX EMPLOYEE COLUMNS from the portal-hardening and E-Verify-status work
(see _EMPLOYEE_BACKFILL below). create_all cannot rescue these: it creates
absent tables but never adds columns to an existing one, so a database
built by `alembic upgrade head` was six columns short of the model and
every ORM insert into employees failed with UndefinedColumn.

Every create/add is existence-guarded, so this is a no-op on databases
that already picked the schema up from create_all.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e8"
down_revision: Union[str, None] = "c9d0e1f2a3b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


# Employee columns that landed as model attributes without a migration.
# portal_token_last_used / portal_token_expires_at came with the portal
# hardening pass (90-day idle + 1-year hard expiry); the everify_* columns
# came with the E-Verify record-keeping shim. b8c9d0e1f2a3 added only
# portal_token and everify_case_number.
#
# create_all() could not paper over these the way it does for whole missing
# tables — it creates absent TABLES but never adds columns to a table that
# already exists. So on a database built by `alembic upgrade head` the
# employees table was permanently six columns short of the model, and every
# ORM insert into employees failed with UndefinedColumn.
_EMPLOYEE_BACKFILL = (
    ("portal_token_last_used", sa.DateTime(timezone=True)),
    ("portal_token_expires_at", sa.DateTime(timezone=True)),
    ("everify_status", sa.String(30)),
    ("everify_submitted_at", sa.DateTime(timezone=True)),
    ("everify_closed_at", sa.DateTime(timezone=True)),
    ("everify_notes", sa.Text()),
)


def upgrade() -> None:
    for column, coltype in _EMPLOYEE_BACKFILL:
        if not _has_column("employees", column):
            op.add_column("employees", sa.Column(column, coltype, nullable=True))

    if not _has_table("document_audits"):
        op.create_table(
            "document_audits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("doc_type", sa.String(20), nullable=False),
            sa.Column("doc_key", sa.String(80), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_document_audits_doc_type", "document_audits", ["doc_type"])
        op.create_index("ix_document_audits_doc_key", "document_audits", ["doc_key"])
        op.create_index(
            "ix_document_audits_content_hash", "document_audits", ["content_hash"]
        )
        op.create_index(
            "ix_document_audits_created_at", "document_audits", ["created_at"]
        )

    if not _has_table("login_attempts"):
        op.create_table(
            "login_attempts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ip", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(255), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=True),
        )
        op.create_index(
            "ix_login_attempts_created_at", "login_attempts", ["created_at"]
        )
        op.create_index("ix_login_attempts_success", "login_attempts", ["success"])

    if not _has_table("portal_accesses"):
        op.create_table(
            "portal_accesses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "employee_id",
                sa.Integer(),
                sa.ForeignKey("employees.id"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ip", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(255), nullable=True),
            sa.Column("path", sa.String(200), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=True),
        )
        op.create_index(
            "ix_portal_accesses_employee_id", "portal_accesses", ["employee_id"]
        )
        op.create_index(
            "ix_portal_accesses_created_at", "portal_accesses", ["created_at"]
        )
        op.create_index("ix_portal_accesses_success", "portal_accesses", ["success"])

    if not _has_table("reseller_permits"):
        op.create_table(
            "reseller_permits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entity_type", sa.String(20), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=True),
            sa.Column("jurisdiction", sa.String(20), nullable=False),
            sa.Column("permit_number", sa.String(50), nullable=False),
            sa.Column("issued_at", sa.Date(), nullable=True),
            sa.Column("expires_at", sa.Date(), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_by", sa.String(100), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )
        for column in (
            "entity_type",
            "entity_id",
            "jurisdiction",
            "permit_number",
            "expires_at",
            "is_active",
        ):
            op.create_index(
                f"ix_reseller_permits_{column}", "reseller_permits", [column]
            )


def downgrade() -> None:
    # These tables predate the migration chain; dropping them would delete
    # audit history that create_all would silently rebuild empty. Left in
    # place deliberately — this migration is additive-only.
    pass
