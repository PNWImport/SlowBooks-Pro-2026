"""Provider transport/prompt contracts; httpx mock transports only."""

import httpx
import pytest

from app.services import ai_service as ai


def test_insights_prompt_metrics_rankings_and_window():
    dashboard = {
        "revenue_by_customer": {"Small": 20, "Large": 80},
        "expenses_by_category": {"Supplies": 25},
        "revenue_trend": {f"2026-{month:02d}": month for month in range(1, 8)},
        "ar_aging": {"current": {"Owes": 10}, "over_30": {"Owes": 5, "Other": 2}},
        "ap_aging": {"current": {"Vendor": 4}},
        "dso": 12.5,
        "cash_forecast": [{"net": 10, "collections": 20, "payments": 10}, {"net": 30}],
        "period": {"name": "custom", "start": "2026-01-01", "end": "2026-07-31"},
    }
    prompt = ai.build_insights_prompt(dashboard, "Synthetic company")
    for expected in [
        "Synthetic company",
        "CUSTOM (2026-01-01 → 2026-07-31)",
        "Revenue:     $100",
        "Expenses:    $25",
        "Net income:  $75",
        "Margin:      75.0%",
        "DSO:         12.5 days",
        "Owes: $15 open",
        "Vendor: $4 open",
        "ending at $30 net.",
    ]:
        assert expected in prompt
    assert prompt.index("Large: $80") < prompt.index("Small: $20")
    assert "2026-01: $1" not in prompt and "2026-02: $2" in prompt
    empty = ai.build_insights_prompt({})
    assert "the business" in empty and "(no data)" in empty
    assert "Margin:      0.0%" in empty


@pytest.mark.parametrize("provider", list(ai.PROVIDERS))
def test_each_provider_returns_text_through_mock_transport(provider):
    requests = []

    def respond(request):
        requests.append(request)
        if provider == "anthropic":
            body = {"content": [{"type": "text", "text": "Synthetic result"}]}
        elif provider == "gemini":
            body = {
                "candidates": [{"content": {"parts": [{"text": "Synthetic result"}]}}]
            }
        else:
            body = {"choices": [{"message": {"content": "Synthetic result"}}]}
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = ai.generate_insights(
            provider,
            "synthetic-key",
            "synthetic-model",
            {},
            "Synthetic company",
            account_id="a" * 32,
            worker_url="https://93.184.216.34/v1/chat/completions",
            endpoint_url="https://93.184.216.34/v1",
            client=client,
        )
    assert result["insights"] == "Synthetic result"
    assert result["provider"] == provider and result["model"] == "synthetic-model"
    assert result["generated_at"]
    assert "synthetic-key" not in str(result)
    assert len(requests) == 1 and requests[0].method == "POST"
    assert b"Synthetic company" in requests[0].content


@pytest.mark.parametrize("failure", ["network", "http", "not-json", "empty"])
def test_provider_failure_messages_do_not_expose_credentials(failure):
    def respond(request):
        if failure == "network":
            raise httpx.ConnectError(
                "synthetic-key embedded in transport error", request=request
            )
        if failure == "http":
            return httpx.Response(500, text="synthetic-key " + "x" * 900)
        if failure == "not-json":
            return httpx.Response(200, text="not JSON")
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ai.AIProviderError) as exc:
            ai.call_provider(
                "openai",
                "synthetic-key",
                "synthetic-model",
                "system",
                "user",
                client=client,
            )
    assert "synthetic-key" not in str(exc.value)
    assert len(str(exc.value)) < 550
