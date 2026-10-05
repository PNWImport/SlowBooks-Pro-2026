"""QBO API status, callback, and transaction failure boundaries."""

import pytest

from app.models.settings import Settings
from app.routes import qbo as routes
from app.services import qbo_service
from tests import test_qbo_oauth_service as oauth_helpers

configure = oauth_helpers.configure
oauth_remote = oauth_helpers.oauth_remote


@pytest.fixture
def connected(db_session):
    configure(
        db_session,
        qbo_access_token="synthetic-access",
        qbo_refresh_token="synthetic-refresh",
        qbo_realm_id="realm",
    )


def test_auth_url_and_callback(client, db_session, oauth_remote):
    configure(db_session)
    assert client.get("/api/qbo/auth-url").json() == {
        "url": "https://example.invalid/authorize"
    }
    state = qbo_service._get_setting(db_session, "qbo_oauth_state")
    response = client.get(
        "/api/qbo/callback",
        params={"code": "synthetic-code", "state": state, "realmId": "realm"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/#/qbo"
    assert (
        client.get(
            "/api/qbo/callback",
            params={"code": "synthetic-code", "state": state, "realmId": "realm"},
        ).status_code
        == 400
    )
    assert client.post("/api/qbo/disconnect").json() == {"status": "disconnected"}
    assert client.get("/api/qbo/status").json()["connected"] is False


def test_auth_url_remote_failure(client, oauth_remote, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic authorization failure")

    monkeypatch.setattr(oauth_remote[1], "get_authorization_url", fail)
    response = client.get("/api/qbo/auth-url")
    assert response.status_code == 400
    assert "check that Client ID" in response.json()["detail"]
    assert "synthetic authorization failure" not in response.text


def test_callback_exchange_failure(client, db_session, oauth_remote, monkeypatch):
    configure(db_session, qbo_oauth_state="expected")

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic exchange failure")

    monkeypatch.setattr(oauth_remote[1], "get_bearer_token", fail)
    response = client.get(
        "/api/qbo/callback",
        params={"code": "code", "state": "expected", "realmId": "realm"},
    )
    assert response.status_code == 500
    assert "synthetic exchange failure" not in response.text
    assert not qbo_service.is_connected(db_session)


@pytest.mark.parametrize("fail", [False, True])
def test_status_never_returns_tokens(client, connected, monkeypatch, fail):
    def company(db):
        if fail:
            raise RuntimeError("synthetic company failure")
        return "Synthetic Company"

    monkeypatch.setattr(qbo_service, "get_company_name", company)
    response = client.get("/api/qbo/status")
    assert response.json() == {
        "connected": True,
        "company_name": "(unable to fetch)" if fail else "Synthetic Company",
        "realm_id": "realm",
    }
    assert "synthetic-access" not in response.text
    assert "synthetic-refresh" not in response.text


@pytest.mark.parametrize(
    "path", ["import", "export", "import/customers", "export/customers"]
)
def test_sync_requires_connection(client, path):
    response = client.post(f"/api/qbo/{path}")
    assert response.status_code == 400
    assert response.json()["detail"] == "Not connected to QuickBooks Online"


@pytest.mark.parametrize("direction", ["import", "export"])
def test_unknown_entity_is_rejected(client, connected, direction):
    response = client.post(f"/api/qbo/{direction}/invalid")
    assert response.status_code == 400
    assert "Unknown entity type" in response.json()["detail"]


@pytest.mark.parametrize("direction", ["import", "export"])
@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_sync_commits_or_rolls_back(
    client, db_session, connected, monkeypatch, direction, single, fail
):
    def operation(db):
        db.add(Settings(key="synthetic_sync_marker", value="written"))
        db.flush()
        if fail:
            raise RuntimeError("synthetic sync failure")
        if single:
            return {
                "imported" if direction == "import" else "exported": 1,
                "errors": [],
            }
        # The all-entity orchestrator owns its successful commit.
        db.commit()
        return {"customers": 1, "errors": []}

    if single:
        mapping = (
            routes._IMPORT_ENTITY_MAP
            if direction == "import"
            else routes._EXPORT_ENTITY_MAP
        )
        monkeypatch.setitem(mapping, "customers", operation)
    else:
        service = routes.qbo_import if direction == "import" else routes.qbo_export
        monkeypatch.setattr(service, f"{direction}_all", operation)
    response = client.post(f"/api/qbo/{direction}" + ("/customers" if single else ""))
    assert response.status_code == (500 if fail else 200)
    assert "synthetic sync failure" not in response.text
    assert db_session.query(Settings).filter_by(
        key="synthetic_sync_marker"
    ).count() == (0 if fail else 1)
    if not fail:
        assert response.json()["errors"] == []


def test_callback_without_cookie_consumes_state_once(
    unauthed_client, db_session, oauth_remote
):
    configure(db_session)
    qbo_service.get_auth_url(db_session)
    state = qbo_service._get_setting(db_session, "qbo_oauth_state")
    params = {"code": "synthetic-code", "state": state, "realmId": "realm"}
    response = unauthed_client.get(
        "/api/qbo/callback", params=params, follow_redirects=False
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/#/qbo"
    assert qbo_service._get_setting(db_session, "qbo_oauth_state") == ""
    assert unauthed_client.get("/api/qbo/callback", params=params).status_code == 400
    assert len([call for call in oauth_remote[0] if call[0] == "exchange"]) == 1
    assert unauthed_client.get("/api/qbo/auth-url").status_code == 401
    assert unauthed_client.post("/api/qbo/disconnect").status_code == 401


@pytest.mark.parametrize("state", [None, "", "wrong"])
def test_public_callback_rejects_invalid_state_without_provider(
    unauthed_client, db_session, oauth_remote, state
):
    configure(db_session, qbo_oauth_state="expected")
    params = {"code": "code", "realmId": "realm"}
    if state is not None:
        params["state"] = state
    response = unauthed_client.get("/api/qbo/callback", params=params)
    assert response.status_code == (422 if state is None else 400)
    assert oauth_remote[0] == []
    assert not qbo_service.is_connected(db_session)


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_public_callback_never_echoes_provider_error(
    unauthed_client, db_session, oauth_remote, monkeypatch, error_type
):
    configure(db_session, qbo_oauth_state="expected")

    def fail(*args, **kwargs):
        raise error_type("synthetic-private-provider-response")

    monkeypatch.setattr(oauth_remote[1], "get_bearer_token", fail)
    response = unauthed_client.get(
        "/api/qbo/callback",
        params={"code": "code", "state": "expected", "realmId": "realm"},
    )
    assert response.status_code == (400 if error_type is ValueError else 500)
    assert "synthetic-private" not in response.text
    assert not qbo_service.is_connected(db_session)


def test_iif_route_failure_rolls_back_without_echoing(client, db_session, monkeypatch):
    from app.routes import iif

    def fail(db, text):
        db.add(Settings(key="synthetic_iif_marker", value="written"))
        db.flush()
        raise RuntimeError("synthetic-private-sql-parameters")

    monkeypatch.setattr(iif, "import_all", fail)
    response = client.post(
        "/api/iif/import", files={"file": ("sample.iif", b"!ACCNT\tNAME\n")}
    )
    assert response.status_code == 500
    assert "synthetic-private" not in response.text
    assert db_session.query(Settings).filter_by(key="synthetic_iif_marker").count() == 0
