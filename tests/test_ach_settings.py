# Saved company ACH details: encrypted at rest, masked on read, revealed
# only with the bank-details permission plus the caller's password, and the
# same permission gates producing an ACH file.

from fastapi.testclient import TestClient

from app.main import app
from app.models.audit import AuditLog
from app.models.settings import Settings
from app.models.users import ROLE_BOOKKEEPER, ROLE_READONLY, User
from app.services import auth as auth_service
from app.services.crypto import is_encrypted

FIXTURE_PW = "test-password-123"
DETAILS = {
    "immediate_destination": "021000021",
    "immediate_origin": "911234567",
    "originating_dfi_id": "02100002",
    "company_account": "9876543210",
}


def _save(client, **overrides):
    return client.put("/api/payroll/ach-settings", json={**DETAILS, **overrides})


def _mk_user(db, username, role, bank=False):
    u = User(
        username=username,
        display_name=username.title(),
        password_hash=auth_service.hash_password(f"{username}-password-1"),
        role=role,
        is_active=True,
        can_access_bank_details=bank,
    )
    db.add(u)
    db.commit()
    return u


def _login_as(client, username):
    client.post("/api/auth/logout")
    r = client.post(
        "/api/auth/login",
        json={"username": username, "password": f"{username}-password-1"},
    )
    assert r.status_code == 200, r.text


def _processed_run(client):
    emp = client.post(
        "/api/employees",
        json={"first_name": "Ada", "last_name": "Lovelace", "pay_rate": 25},
    ).json()
    client.post(
        f"/api/employees/{emp['id']}/bank-accounts",
        json={
            "account_kind": "checking",
            "routing_number": "021000021",
            "account_number": "123456789",
            "deposit_type": "full",
        },
    )
    run = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-09-14",
            "period_end": "2026-09-27",
            "pay_date": "2026-10-02",
            "stubs": [{"employee_id": emp["id"], "hours": 80}],
        },
    ).json()
    assert client.post(f"/api/payroll/{run['id']}/process").status_code == 200
    return run


# --- storage + masking ------------------------------------------------------


def test_saved_details_are_encrypted_at_rest(client, db_session):
    assert _save(client).status_code == 200
    rows = db_session.query(Settings).filter(Settings.key.like("ach_%")).all()
    assert len(rows) == 4
    for row in rows:
        assert is_encrypted(row.value)
        assert "9876543210" not in row.value


def test_read_is_masked_and_settings_api_never_returns_them(client):
    _save(client)
    view = client.get("/api/payroll/ach-settings").json()
    assert view["configured"] is True
    assert view["values"]["company_account"] == "•••• 3210"
    assert "9876543210" not in str(view)
    settings = client.get("/api/settings").json()
    assert not [k for k in settings if k.startswith("ach_")]


def test_blank_field_keeps_saved_value(client):
    _save(client)
    r = client.put("/api/payroll/ach-settings", json={"company_account": "55556666"})
    assert r.status_code == 200
    values = client.post(
        "/api/payroll/ach-settings/reveal", json={"password": FIXTURE_PW}
    ).json()["values"]
    assert values["company_account"] == "55556666"
    assert values["immediate_destination"] == "021000021"


def test_bad_values_rejected(client):
    assert _save(client, immediate_destination="123456789").status_code == 400
    assert _save(client, originating_dfi_id="1234").status_code == 400
    assert _save(client, immediate_origin="12-34").status_code == 400
    assert _save(client, company_account="12 34").status_code == 400


# --- reveal -----------------------------------------------------------------


def test_reveal_needs_the_right_password_and_is_audited(client, db_session):
    _save(client)
    wrong = client.post("/api/payroll/ach-settings/reveal", json={"password": "not-it"})
    assert wrong.status_code == 403  # 401 would sign the SPA out
    r = client.post("/api/payroll/ach-settings/reveal", json={"password": FIXTURE_PW})
    assert r.status_code == 200
    assert r.json()["values"] == DETAILS
    assert db_session.query(AuditLog).filter_by(action="REVEAL").count() == 1


# --- export -----------------------------------------------------------------


def test_export_uses_saved_details_and_is_audited(client, db_session, seed_accounts):
    run = _processed_run(client)
    missing = client.post(f"/api/payroll/{run['id']}/nacha", json={})
    assert missing.status_code == 400
    assert "Save your company's ACH details" in missing.json()["detail"]
    _save(client)
    r = client.post(f"/api/payroll/{run['id']}/nacha", json={})
    assert r.status_code == 200, r.text
    assert "9876543210" in r.text  # offsetting company debit
    assert (
        db_session.query(AuditLog)
        .filter_by(action="ACH_EXPORT", table_name="pay_runs", record_id=run["id"])
        .count()
        == 1
    )


# --- who may -----------------------------------------------------------------


def test_bookkeeper_needs_the_flag(client, db_session, seed_accounts):
    run = _processed_run(client)
    _save(client)
    keeper = _mk_user(db_session, "keeper", ROLE_BOOKKEEPER)
    _login_as(client, "keeper")

    assert client.get("/api/payroll/ach-settings").json()["can_access"] is False
    assert _save(client).status_code == 403
    reveal = client.post(
        "/api/payroll/ach-settings/reveal", json={"password": "keeper-password-1"}
    )
    assert reveal.status_code == 403
    assert client.post(f"/api/payroll/{run['id']}/nacha", json={}).status_code == 403

    keeper.can_access_bank_details = True
    db_session.commit()
    assert client.get("/api/payroll/ach-settings").json()["can_access"] is True
    reveal = client.post(
        "/api/payroll/ach-settings/reveal", json={"password": "keeper-password-1"}
    )
    assert reveal.status_code == 200
    assert client.post(f"/api/payroll/{run['id']}/nacha", json={}).status_code == 200

    # Revoking takes effect on the next request, not the next login.
    keeper.can_access_bank_details = False
    db_session.commit()
    assert client.post(f"/api/payroll/{run['id']}/nacha", json={}).status_code == 403


def test_reveal_checks_the_signed_in_users_own_password(client, db_session):
    _save(client)
    _mk_user(db_session, "keeper", ROLE_BOOKKEEPER, bank=True)
    _login_as(client, "keeper")
    r = client.post("/api/payroll/ach-settings/reveal", json={"password": FIXTURE_PW})
    assert r.status_code == 403  # the admin's password is not this user's


def test_readonly_never_gets_access_even_with_the_flag(client, db_session):
    _save(client)
    _mk_user(db_session, "viewer", ROLE_READONLY, bank=True)
    _login_as(client, "viewer")
    view = client.get("/api/payroll/ach-settings").json()
    assert view["can_access"] is False
    assert "9876543210" not in str(view)


def test_api_tokens_never_get_access(client, seed_accounts):
    run = _processed_run(client)
    _save(client)
    token = client.post("/api/tokens", json={"label": "agent", "role": "admin"})
    bearer = TestClient(app)
    bearer.headers["Authorization"] = f"Bearer {token.json()['token']}"
    assert bearer.post(f"/api/payroll/{run['id']}/nacha", json={}).status_code == 403
    reveal = bearer.post(
        "/api/payroll/ach-settings/reveal", json={"password": FIXTURE_PW}
    )
    assert reveal.status_code == 403


def test_admin_manages_the_flag_on_the_users_api(client):
    created = client.post(
        "/api/users",
        json={
            "username": "keeper",
            "password": "keeper-password-1",
            "role": "bookkeeper",
            "can_access_bank_details": True,
        },
    ).json()
    assert created["can_access_bank_details"] is True
    updated = client.put(
        f"/api/users/{created['id']}", json={"can_access_bank_details": False}
    ).json()
    assert updated["can_access_bank_details"] is False
    users = {u["username"]: u for u in client.get("/api/users").json()}
    assert users["admin"]["can_access_bank_details"] is True
