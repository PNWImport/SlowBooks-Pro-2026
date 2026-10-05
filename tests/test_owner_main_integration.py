"""Branch features must retain the owner-main security contract."""

import pytest

from app.main import _is_hr_sensitive
from tests.test_rbac_users import _login_as, _mk_user

BRANCH_PRIVATE_PATHS = (
    "/api/benefit-coverage/plans",
    "/api/contractor-runs",
    "/api/pay-schedules",
    "/api/locations",
    "/api/hr/reviews",
    "/api/workers-comp/premium-report",
    "/api/reports/payroll-journal",
    "/api/reports/deduction-register",
    "/api/reports/contractor-payments",
    "/api/audit",
    "/api/document-audits",
)


@pytest.mark.parametrize("role", ["bookkeeper", "readonly"])
def test_branch_hr_routes_are_admin_only(client, db_session, role):
    _mk_user(db_session, "branch-reviewer", "synthetic-password-123", role)
    _login_as(client, "branch-reviewer", "synthetic-password-123")
    for path in BRANCH_PRIVATE_PATHS:
        assert _is_hr_sensitive(path), path
        for method in ("GET", "POST"):
            assert client.request(method, path, json={}).status_code == 403, path
    assert client.get("/api/customers").status_code == 200
    assert client.get("/api/employees").status_code == 200


def test_single_merge_head_preserves_both_histories():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["c7d1e4a92b30"]
    revisions = {revision.revision for revision in script.walk_revisions()}
    assert {
        "fa12bc34de56",
        "d6e7f8a9b0c1",
        "ff00aabb1122",
        "ac14bd25ce36",
        "a9b0c1d2e3f4",
    } <= revisions
