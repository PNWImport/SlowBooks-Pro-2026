"""Malformed upstream JSON must fail safely without external network calls."""

import httpx
import pytest

from app.services import ai_service as ai


@pytest.mark.parametrize(
    "provider,body",
    [
        ("anthropic", []),
        ("anthropic", None),
        ("openai", {"choices": [{"message": {"content": {"unexpected": "object"}}}]}),
        ("anthropic", {"content": [{"type": "text", "text": ["unexpected"]}]}),
    ],
)
def test_nontext_provider_response_is_controlled_error(provider, body):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ai.AIProviderError, match="response"):
            ai.call_provider(
                provider,
                "synthetic-key",
                "synthetic-model",
                "system",
                "user",
                client=client,
            )


@pytest.mark.parametrize(
    "wire,body",
    [
        ("openai", []),
        ("openai", {"choices": [None]}),
        ("openai", {"choices": [{"message": {"tool_calls": [None]}}]}),
        ("anthropic", None),
        ("gemini", {"candidates": [None]}),
    ],
)
def test_malformed_tool_envelopes_do_not_raise(wire, body):
    assert ai._extract_tool_calls(wire, body) == []


@pytest.mark.parametrize(
    "provider,body,expected",
    [
        (
            "openai",
            {"choices": [{"message": {"content": "Synthetic answer"}}]},
            "Synthetic answer",
        ),
        (
            "anthropic",
            {"content": [{"type": "text", "text": "Synthetic answer"}]},
            "Synthetic answer",
        ),
        (
            "gemini",
            {
                "candidates": [
                    {"content": {"parts": [{"text": "Synthetic "}, {"text": "answer"}]}}
                ]
            },
            "Synthetic answer",
        ),
    ],
)
def test_text_formats_remain_compatible(provider, body, expected):
    assert ai.parse_response(provider, body) == expected
