"""Legacy password helpers and direct dependency boundary behavior."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.services import auth
from tests.test_rbac_users import _mk_user


def test_legacy_password_setup_and_verification(db_session):
    assert auth.ensure_admin_user(db_session) is None
    assert not auth.password_is_set(db_session)
    assert not auth.check_password(db_session, "synthetic-password")
    auth.set_password(db_session, "synthetic-password")
    assert auth.check_password(db_session, "synthetic-password")
    assert not auth.check_password(db_session, "incorrect-password")
    assert not auth.verify_password("password", "not-an-argon-hash")
    admin = auth.ensure_admin_user(db_session)
    previous_credential = auth.session_credential(admin)
    auth.set_password(db_session, "replacement-password")
    db_session.refresh(admin)
    assert auth.verify_password("replacement-password", admin.password_hash)
    assert auth.session_credential(admin) != previous_credential


def test_multiple_users_require_username(db_session):
    _mk_user(db_session, "one", "synthetic-password", "admin")
    _mk_user(db_session, "two", "synthetic-password", "readonly")
    assert auth.authenticate(db_session, "synthetic-password", username=" ") is None


@pytest.mark.parametrize("authenticated", [False, None, "true", 1])
def test_direct_auth_dependency_requires_boolean_true(authenticated):
    request = Request({"type": "http", "session": {"authenticated": authenticated}})
    with pytest.raises(HTTPException) as result:
        auth.require_auth(request)
    assert result.value.status_code == 401


def test_direct_auth_dependency_accepts_authenticated_session():
    request = Request({"type": "http", "session": {"authenticated": True}})
    assert auth.require_auth(request) is None
