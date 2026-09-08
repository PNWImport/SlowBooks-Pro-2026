"""
Smoke test for the analytics module — we don't care about exact numbers,
just that an authenticated client can reach the dashboard and the PUT
/ai-config endpoint enforces SSRF validation.
"""


def test_dashboard_auth_required(unauthed_client):
    r = unauthed_client.get("/api/analytics/dashboard")
    assert r.status_code == 401


def test_dashboard_reachable_when_authed(authed_client):
    r = authed_client.get("/api/analytics/dashboard")
    assert r.status_code == 200, r.text


def test_ai_config_rejects_bad_account_id(authed_client):
    r = authed_client.put(
        "/api/analytics/ai-config",
        json={
            "provider": "cloudflare",
            "cloudflare_account_id": "not-32-hex-chars",
        },
    )
    assert r.status_code == 400


def test_ai_config_rejects_bad_worker_url(authed_client):
    r = authed_client.put(
        "/api/analytics/ai-config",
        json={
            "provider": "cloudflare_worker",
            "worker_url": "http://127.0.0.1/",
        },
    )
    assert r.status_code == 400


def test_ai_query_requires_auth(unauthed_client):
    r = unauthed_client.post("/api/analytics/ai-query?question=hello")
    assert r.status_code == 401
