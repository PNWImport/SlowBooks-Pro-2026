"""Portal aliases, validation and session boundary contracts."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.payroll import Employee
from app.routes import portal


def _employee(db_session):
    employee = Employee(
        first_name="Boundary", last_name="Portal", portal_token="p" * 32, is_active=True
    )
    db_session.add(employee)
    db_session.commit()
    return employee


def test_claim_aliases_logout_bank_errors_and_missing_cookie(client, db_session):
    employee = _employee(db_session)
    token = employee.portal_token
    for suffix, destination in (
        ("paystubs", "/portal/paystubs"),
        ("profile", "/portal/profile"),
        ("bank", "/portal/bank"),
        ("pto", "/portal/pto"),
    ):
        response = client.get(f"/portal/{token}/{suffix}", follow_redirects=False)
        assert (
            response.status_code == 303 and response.headers["location"] == destination
        )

    client.cookies.clear()
    assert client.get("/portal/profile").status_code == 401
    client.cookies.set(portal.PORTAL_COOKIE_NAME, "invalid-token", path="/portal")
    assert client.get("/portal/profile").status_code == 404
    client.cookies.set(portal.PORTAL_COOKIE_NAME, token, path="/portal")
    invalid_account = client.post(
        "/portal/bank",
        data={
            "account_kind": "checking",
            "routing_number": "021000021",
            "account_number": "abc",
            "deposit_type": "full",
        },
        follow_redirects=False,
    )
    assert (
        invalid_account.status_code == 303
        and "Account+number" in invalid_account.headers["location"]
    )
    invalid_choice = client.post(
        "/portal/bank",
        data={
            "account_kind": "bad",
            "routing_number": "021000021",
            "account_number": "123",
            "deposit_type": "full",
        },
        follow_redirects=False,
    )
    assert "Invalid+selection" in invalid_choice.headers["location"]
    saved = client.post(
        "/portal/bank",
        data={
            "account_kind": "checking",
            "routing_number": "021000021",
            "account_number": "12345678",
            "deposit_type": "full",
        },
        follow_redirects=False,
    )
    assert saved.headers["location"] == "/portal/bank?saved=1"
    invalid_token_post = client.post(
        "/portal/not-a-token/profile",
        data={"filing_status": "single"},
    )
    assert invalid_token_post.status_code == 404
    logout = client.post("/portal/logout", follow_redirects=False)
    assert logout.status_code == 303 and logout.headers["location"] == "/portal/"


def test_helper_validation_audit_failure_and_empty_favicon(db_session, monkeypatch):
    employee = _employee(db_session)
    with pytest.raises(HTTPException, match="Invalid filing status"):
        portal._save_profile(
            employee,
            filing_status="bad",
            multiple_jobs=False,
            dependents_amount=0,
            other_income_annual=0,
            deductions_annual=0,
            extra_withholding=0,
            address1="",
            address2="",
            city="",
            state="",
            zip="",
            db=db_session,
        )
    with pytest.raises(HTTPException, match="Invalid PTO type"):
        portal._request_pto(
            employee,
            start_date="2026-01-01",
            end_date="2026-01-02",
            hours=1,
            pto_type="bad",
            notes="",
            db=db_session,
        )
    with pytest.raises(HTTPException, match="Dates must"):
        portal._request_pto(
            employee,
            start_date="bad",
            end_date="bad",
            hours=1,
            pto_type="vacation",
            notes="",
            db=db_session,
        )

    fake_db = SimpleNamespace(
        add=lambda *_: (_ for _ in ()).throw(RuntimeError()),
        rollback=lambda: setattr(fake_db, "rolled_back", True),
    )
    request = SimpleNamespace(headers={}, url=SimpleNamespace(path="/portal/"))
    portal._record_portal_access(fake_db, request, None, False)
    assert fake_db.rolled_back is True
    monkeypatch.setattr(portal, "get_all_settings", lambda _db: {})
    assert portal.portal_favicon(db_session).status_code == 204
    monkeypatch.setattr(
        portal,
        "get_all_settings",
        lambda _db: {"company_logo_path": "../../etc/passwd"},
    )
    assert portal.portal_favicon(db_session).status_code == 204
    monkeypatch.setattr(
        portal,
        "get_all_settings",
        lambda _db: {"company_logo_path": "static/missing.png"},
    )
    assert portal.portal_favicon(db_session).status_code == 204
    monkeypatch.setattr(
        portal,
        "get_all_settings",
        lambda _db: {"company_logo_path": "static/js/desktop_shim.js"},
    )
    response = portal.portal_favicon(db_session)
    assert response.media_type == "image/png"
