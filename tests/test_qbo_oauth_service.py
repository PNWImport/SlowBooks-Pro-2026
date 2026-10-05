"""OAuth state, encrypted token persistence, refresh, and disconnect contracts."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.settings import Settings
from app.services import qbo_service as qbo


@pytest.fixture
def oauth_remote(monkeypatch):
    calls = []

    class Auth:
        access_token = "synthetic-access"
        refresh_token = "synthetic-refresh"
        expires_in = 3600

        def __init__(self, **kwargs):
            calls.append(("construct", kwargs))

        def get_authorization_url(self, **kwargs):
            calls.append(("authorize", kwargs))
            return "https://example.invalid/authorize"

        def get_bearer_token(self, code, realm_id):
            calls.append(("exchange", {"code": code, "realm_id": realm_id}))

        def refresh(self, **kwargs):
            calls.append(("refresh", kwargs))

    monkeypatch.setattr(qbo, "AuthClient", Auth)
    monkeypatch.setattr(qbo, "QuickBooks", lambda **kwargs: SimpleNamespace(**kwargs))
    return calls, Auth


def configure(db, **overrides):
    values = {
        "qbo_client_id": "synthetic-client",
        "qbo_client_secret": "synthetic-secret",
        "qbo_redirect_uri": "http://localhost/callback",
        "qbo_environment": "sandbox",
    }
    values.update(overrides)
    for key, value in values.items():
        qbo._set_setting(db, key, value)
    db.commit()


def test_oauth_exchange_is_single_use_and_encrypted(db_session, oauth_remote):
    configure(db_session)
    assert qbo.get_auth_url(db_session) == "https://example.invalid/authorize"
    state = qbo._get_setting(db_session, "qbo_oauth_state")
    assert len(state) == 32
    assert oauth_remote[0][-1][1]["state_token"] == state
    before = int(datetime.now(timezone.utc).timestamp())
    qbo.handle_callback(db_session, "synthetic-code", state, "realm-1")
    assert qbo.is_connected(db_session)
    assert qbo._get_setting(db_session, "qbo_oauth_state") == ""
    assert qbo._get_setting(db_session, "qbo_access_token") == "synthetic-access"
    assert int(qbo._get_setting(db_session, "qbo_token_expires_at")) >= before + 3600
    raw = db_session.query(Settings).filter_by(key="qbo_access_token").one().value
    assert "synthetic-access" not in raw
    with pytest.raises(ValueError, match="state mismatch"):
        qbo.handle_callback(db_session, "synthetic-code", state, "realm-1")
    assert len([c for c in oauth_remote[0] if c[0] == "exchange"]) == 1
    qbo.disconnect(db_session)
    assert not qbo.is_connected(db_session)
    for key in (
        "qbo_access_token",
        "qbo_refresh_token",
        "qbo_realm_id",
        "qbo_token_expires_at",
        "qbo_oauth_state",
    ):
        assert qbo._get_setting(db_session, key) == ""


@pytest.mark.parametrize("state", ["", "wrong"])
def test_invalid_state_never_contacts_provider(db_session, oauth_remote, state):
    configure(db_session, qbo_oauth_state="expected")
    with pytest.raises(ValueError, match="state mismatch"):
        qbo.handle_callback(db_session, "code", state, "realm")
    assert oauth_remote[0] == []


@pytest.mark.parametrize("expiry", ["", "invalid", "9999999999"])
def test_unneeded_refresh_does_not_contact_provider(db_session, oauth_remote, expiry):
    configure(db_session, qbo_token_expires_at=expiry)
    qbo._refresh_if_needed(db_session)
    assert oauth_remote[0] == []


@pytest.mark.parametrize("rotate", [False, True])
def test_expired_token_refresh_and_client_wiring(db_session, oauth_remote, rotate):
    configure(
        db_session,
        qbo_token_expires_at="1",
        qbo_access_token="old-access",
        qbo_refresh_token="old-refresh",
        qbo_realm_id="realm",
    )
    if not rotate:
        oauth_remote[1].refresh_token = None
        oauth_remote[1].expires_in = None
    client = qbo.get_qbo_client(db_session)
    assert client.company_id == "realm"
    assert client.auth_client.access_token == "synthetic-access"
    assert client.refresh_token == ("synthetic-refresh" if rotate else "old-refresh")
    assert ("refresh", {"refresh_token": "old-refresh"}) in oauth_remote[0]
    assert qbo._get_setting(db_session, "qbo_refresh_token") == client.refresh_token


def test_disconnected_client_is_rejected_without_network(db_session, oauth_remote):
    with pytest.raises(RuntimeError, match="Not connected"):
        qbo.get_qbo_client(db_session)
    assert oauth_remote[0] == []


@pytest.mark.parametrize(
    "response",
    [
        [],
        [SimpleNamespace(CompanyName="Synthetic Company")],
        [SimpleNamespace(CompanyName=None)],
    ],
)
def test_company_name_response(db_session, oauth_remote, monkeypatch, response):
    from quickbooks.objects.company_info import CompanyInfo

    configure(
        db_session,
        qbo_access_token="access",
        qbo_refresh_token="refresh",
        qbo_realm_id="realm",
    )
    monkeypatch.setattr(CompanyInfo, "all", lambda qb: response)
    assert qbo.get_company_name(db_session) == (
        "Synthetic Company" if response and response[0].CompanyName else ""
    )


def test_company_name_failure_returns_empty(db_session, oauth_remote):
    assert qbo.get_company_name(db_session) == ""


def test_callback_without_expiry_or_tokens(db_session, oauth_remote):
    configure(db_session, qbo_oauth_state="expected")
    oauth_remote[1].expires_in = None
    oauth_remote[1].access_token = None
    oauth_remote[1].refresh_token = None
    with pytest.raises(RuntimeError, match="incomplete OAuth tokens"):
        qbo.handle_callback(db_session, "code", "expected", "realm")
    assert not qbo.is_connected(db_session)
    assert qbo._get_setting(db_session, "qbo_token_expires_at") == ""
