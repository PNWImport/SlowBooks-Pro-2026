# Payroll and tax documents name the company from Settings — the same name
# the app shows — not the COMPANY_NAME/EMPLOYER_EIN env vars, which default
# to "My Company" and a blank EIN on an install that never set them.

from app.services.settings_service import company_identity, set_setting

ORIGINATING = {
    "immediate_destination": "021000021",
    "immediate_origin": "911234567",
    "originating_dfi_id": "02100002",
    "company_account": "9876543210",
}


def _set_company(client):
    r = client.put(
        "/api/settings",
        json={
            "company_name": "Cascade Plumbing LLC",
            "company_address1": "412 W Riverside Ave",
            "company_city": "Spokane",
            "company_state": "WA",
            "company_zip": "99201",
            "company_tax_id": "91-1234567",
        },
    )
    assert r.status_code == 200, r.text


def _processed_run_with_deposit(client):
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
    return emp, run


def test_identity_prefers_settings_over_env(db_session, monkeypatch):
    monkeypatch.setattr("app.config.COMPANY_NAME", "Env Co")
    monkeypatch.setattr("app.config.EMPLOYER_EIN", "11-1111111")
    set_setting(db_session, "company_name", "Cascade Plumbing LLC")
    set_setting(db_session, "company_tax_id", "91-1234567")
    set_setting(db_session, "company_address1", "412 W Riverside Ave")
    set_setting(db_session, "company_city", "Spokane")
    set_setting(db_session, "company_state", "WA")
    set_setting(db_session, "company_zip", "99201")
    db_session.commit()
    co = company_identity(db_session)
    assert co["name"] == "Cascade Plumbing LLC"
    assert co["ein"] == "91-1234567"
    assert co["full_address"] == "412 W Riverside Ave, Spokane, WA 99201"


def test_identity_falls_back_to_env_when_settings_blank(db_session, monkeypatch):
    monkeypatch.setattr("app.config.COMPANY_NAME", "Env Co")
    monkeypatch.setattr("app.config.EMPLOYER_EIN", "11-1111111")
    monkeypatch.setattr("app.config.COMPANY_ADDRESS", "1 Env St, Olympia, WA")
    co = company_identity(db_session)
    assert co["name"] == "Env Co"
    assert co["ein"] == "11-1111111"
    assert co["full_address"] == "1 Env St, Olympia, WA"


def test_payroll_ach_file_names_the_settings_company(client, seed_accounts):
    _set_company(client)
    _, run = _processed_run_with_deposit(client)
    r = client.post(f"/api/payroll/{run['id']}/nacha", json=ORIGINATING)
    assert r.status_code == 200, r.text
    batch_header = next(l for l in r.text.split("\n") if l.startswith("5"))
    assert "Cascade Plumbing" in batch_header  # NACHA caps the name at 16
    assert "91-1234567" in batch_header
    assert "My Company" not in r.text


def test_w2_names_the_settings_company(client, seed_accounts):
    _set_company(client)
    emp, _ = _processed_run_with_deposit(client)
    w2 = client.post(f"/api/payroll/forms/w2/{emp['id']}?year=2026").json()
    assert w2["employer_name"] == "Cascade Plumbing LLC"
    assert w2["employer_ein"] == "91-1234567"


def test_ach_file_served_inline_to_the_desktop_shell(client, seed_accounts):
    # WebView2 swallows a fetch() of an attachment, so the SPA sends this
    # header and saves the file itself.
    _, run = _processed_run_with_deposit(client)
    r = client.post(
        f"/api/payroll/{run['id']}/nacha",
        json=ORIGINATING,
        headers={"X-Slowbooks-Desktop": "1"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].startswith("inline")
    assert f"payroll_{run['id']}.ach" in r.headers["content-disposition"]
