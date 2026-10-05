"""AI route contracts with real settings and an offline provider boundary."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.routes import analytics
from app.services import ai_service
from app.services.settings_service import set_setting


@pytest.fixture(autouse=True)
def isolated_insight_cache(monkeypatch):
    monkeypatch.setattr(analytics, "_AI_CACHE", {})


def configure(client):
    response = client.put(
        "/api/analytics/ai-config",
        json={
            "provider": "openai",
            "model": "synthetic-model",
            "api_key": "synthetic-key",
        },
    )
    assert response.status_code == 200, response.text
    assert "synthetic-key" not in response.text


def test_insight_cache_dates_expiry_force_and_config_invalidation(
    authed_client, monkeypatch
):
    configure(authed_client)
    calls = []
    now = [1000]
    monkeypatch.setattr(analytics, "time", SimpleNamespace(time=lambda: now[0]))

    def generate(**kwargs):
        calls.append(kwargs)
        return {"insights": f"Synthetic analysis {len(calls)}"}

    monkeypatch.setattr(analytics, "ai_generate_insights", generate)
    url = "/api/analytics/ai-insights?start_date=2026-01-01&end_date=2026-01-31"
    first = authed_client.post(url)
    assert first.status_code == 200, first.text
    assert first.json()["cached"] is False
    cached = authed_client.post(url).json()
    assert cached["cached"] is True and cached["insights"] == first.json()["insights"]
    assert len(calls) == 1
    assert authed_client.post(url + "&force=true").json()["cached"] is False
    now[0] += analytics._AI_CACHE_TTL_SECONDS + 1
    assert authed_client.post(url).json()["cached"] is False
    assert authed_client.post(url.replace("01-31", "01-30")).json()["cached"] is False
    assert len(calls) == 4
    assert calls[0]["dashboard"]["period"] == {
        "name": "custom",
        "start": "2026-01-01",
        "end": "2026-01-31",
    }
    configure(authed_client)
    assert authed_client.post(url).json()["cached"] is False
    assert len(calls) == 5


@pytest.mark.parametrize(
    "endpoint,boundary",
    [
        ("ai-insights", "ai_generate_insights"),
        ("ai-query?question=summary", "call_with_tools"),
        ("ai-actions/" + next(iter(analytics.AI_ACTIONS)), "ai_run_action"),
    ],
)
def test_provider_errors_are_bounded_and_not_cached(
    authed_client, monkeypatch, endpoint, boundary
):
    configure(authed_client)

    def fail(**kwargs):
        raise ai_service.AIProviderError("Safe provider failure " + "x" * 600)

    monkeypatch.setattr(analytics, boundary, fail)
    response = authed_client.post("/api/analytics/" + endpoint)
    assert response.status_code == 502
    assert len(response.json()["detail"]) == 500
    assert "synthetic-key" not in response.text
    assert analytics._AI_CACHE == {}


@pytest.mark.parametrize(
    "provider,extras,detail",
    [
        ("cloudflare", {}, "cloudflare_account_id"),
        ("cloudflare_worker", {}, "worker_url"),
        ("custom", {}, "model ID"),
        ("custom", {"model": "synthetic-model"}, "endpoint_url"),
    ],
)
def test_provider_specific_requirements_block_calls(
    authed_client, db_session, provider, extras, detail
):
    set_setting(db_session, "ai_provider", provider)
    set_setting(db_session, "ai_api_key", "synthetic-key")
    for key, value in extras.items():
        set_setting(db_session, "ai_" + key, value)
    db_session.commit()
    response = authed_client.post("/api/analytics/ai-insights")
    assert response.status_code == 400
    assert detail in response.json()["detail"]


def test_connectivity_check_trims_reply_and_uses_configured_model(
    authed_client, monkeypatch
):
    configure(authed_client)
    calls = []

    def reply(**kwargs):
        calls.append(kwargs)
        return "  " + "ok" * 150 + "  "

    monkeypatch.setattr(ai_service, "call_provider", reply)
    response = authed_client.post("/api/analytics/ai-config/test")
    assert response.status_code == 200
    assert response.json()["reply"] == "ok" * 100
    assert calls[0]["model"] == "synthetic-model"
    assert response.json()["tested_at"]


def test_query_executor_reads_real_database(authed_client, seed_customer, monkeypatch):
    configure(authed_client)

    def query(**kwargs):
        assert kwargs["max_calls"] == 8
        assert kwargs["user_question"] == "customers"
        data = kwargs["tool_executor"]("list_customers", limit=5)
        assert seed_customer.name in str(data)
        return {"success": True, "final_response": "Synthetic response", "data": data}

    monkeypatch.setattr(analytics, "call_with_tools", query)
    response = authed_client.post("/api/analytics/ai-query?question=customers")
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True


def test_action_receives_resolved_dates_and_reports_validation_error(
    authed_client, monkeypatch
):
    configure(authed_client)
    key = next(iter(analytics.AI_ACTIONS))
    calls = []

    def action(**kwargs):
        calls.append(kwargs)
        return {"analysis": "Synthetic analysis"}

    monkeypatch.setattr(analytics, "ai_run_action", action)
    url = f"/api/analytics/ai-actions/{key}?start_date=2026-01-01&end_date=2026-01-31"
    response = authed_client.post(url)
    assert response.status_code == 200
    assert calls[0]["period_start"] == date(2026, 1, 1)
    assert response.json()["period"]["end"] == "2026-01-31"

    def invalid(**kwargs):
        raise ValueError("Invalid synthetic input " + "x" * 300)

    monkeypatch.setattr(analytics, "ai_run_action", invalid)
    response = authed_client.post(url)
    assert response.status_code == 400
    assert len(response.json()["detail"]) == 200


def test_connectivity_failure_and_missing_configuration(authed_client, monkeypatch):
    url = "/api/analytics/ai-config/test"
    assert authed_client.post(url).status_code == 400
    configure(authed_client)

    def fail(**kwargs):
        raise ai_service.AIProviderError("Synthetic unavailable")

    monkeypatch.setattr(ai_service, "call_provider", fail)
    response = authed_client.post(url)
    assert response.status_code == 502
    assert response.json()["detail"] == "Synthetic unavailable"
    cleared = authed_client.put(
        "/api/analytics/ai-config", json={"provider": "openai", "api_key": ""}
    )
    assert cleared.status_code == 200 and not cleared.json()["has_api_key"]
    assert "No AI API key" in authed_client.post(url).json()["detail"]


def test_corrupt_key_is_unusable_without_exposing_it(db_session, monkeypatch):
    set_setting(db_session, "ai_api_key", "synthetic-corrupt-key")
    db_session.commit()

    def corrupt(value):
        raise ValueError("Synthetic decrypt failure")

    monkeypatch.setattr(analytics, "decrypt_value", corrupt)
    assert analytics._read_ai_config(db_session)["api_key"] == ""


def test_action_catalog_unknown_and_unconfigured(authed_client):
    catalog = authed_client.get("/api/analytics/ai-actions")
    assert catalog.status_code == 200 and catalog.json()["groups"]
    assert (
        authed_client.post("/api/analytics/ai-actions/not-an-action").status_code == 404
    )
    key = next(iter(analytics.AI_ACTIONS))
    assert authed_client.post(f"/api/analytics/ai-actions/{key}").status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "not-a-provider"},
        {
            "provider": "custom",
            "model": "synthetic",
            "endpoint_url": "http://127.0.0.1",
        },
    ],
)
def test_invalid_config_does_not_replace_existing_settings(authed_client, payload):
    configure(authed_client)
    assert (
        authed_client.put("/api/analytics/ai-config", json=payload).status_code == 400
    )
    current = authed_client.get("/api/analytics/ai-config").json()
    assert current["provider"] == "openai" and current["has_api_key"]


def test_error_detail_handles_missing_or_nonstring_message():
    assert (
        analytics._ai_error_detail(ai_service.AIProviderError()) == "AI provider error"
    )
    assert (
        analytics._ai_error_detail(ai_service.AIProviderError(42))
        == "AI provider error"
    )
