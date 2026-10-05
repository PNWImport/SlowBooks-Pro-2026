"""Existing cookies must not outlive changes to account authorization."""

import pytest

from tests.test_rbac_users import _login_as, _mk_user
from app.services.auth import hash_password
from app.services.auth import refresh_session_principal, session_credential


@pytest.mark.parametrize(
    "principal",
    [
        {},
        {"user_id": True, "credential": "invalid"},
        {"user_id": "1", "credential": "invalid"},
        {"user_id": 1, "credential": None},
        {"user_id": 1, "credential": 123},
    ],
)
def test_malformed_session_principal_is_cleared(principal):
    principal["authenticated"] = True
    assert refresh_session_principal(principal) is False
    assert principal == {}


def test_unknown_role_revokes_even_matching_credential(db_session):
    user = _mk_user(db_session, "invalid-role", "synthetic-password-123", "admin")
    user.role = "unrecognized"
    db_session.commit()
    principal = {"user_id": user.id, "credential": session_credential(user)}
    assert refresh_session_principal(principal) is False
    assert principal == {}


def test_display_name_refresh_preserves_valid_session(db_session):
    user = _mk_user(db_session, "rename-display", "synthetic-password-123", "admin")
    principal = {"user_id": user.id, "credential": session_credential(user)}
    user.display_name = "Updated display name"
    db_session.commit()
    assert refresh_session_principal(principal) is True
    assert principal["display_name"] == "Updated display name"
    assert principal["role"] == "admin"


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
