"""Existing cookies must not outlive changes to account authorization."""

import pytest

from tests.test_rbac_users import _login_as, _mk_user
from app.services.auth import hash_password


@pytest.mark.parametrize("change", ["demote", "disable", "password", "delete"])
def test_existing_session_revoked(client, db_session, change):
    user = _mk_user(db_session, "review-admin", "synthetic-password-123", "admin")
    _login_as(client, user.username, "synthetic-password-123")
    cookie = client.cookies.get("slowbooks_session")
    assert client.get("/api/payroll").status_code == 200
    if change == "demote":
        user.role = "readonly"
    elif change == "disable":
        user.is_active = False
    elif change == "password":
        user.password_hash = hash_password("replacement-password-123")
    else:
        db_session.delete(user)
    db_session.commit()
    assert client.get("/api/payroll").status_code == 401
    # Replaying the original signed cookie must also fail.
    client.cookies.clear()
    client.cookies.set("slowbooks_session", cookie)
    assert client.get("/api/auth/status").json()["authenticated"] is False
    assert client.get("/api/payroll").status_code == 401


def test_demoted_user_can_sign_in_with_current_role(client, db_session):
    user = _mk_user(db_session, "review-admin", "synthetic-password-123", "admin")
    _login_as(client, user.username, "synthetic-password-123")
    user.role = "readonly"
    db_session.commit()
    _login_as(client, user.username, "synthetic-password-123")
    assert client.get("/api/customers").status_code == 200
    assert client.get("/api/payroll").status_code == 403
