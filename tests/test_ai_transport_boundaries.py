"""AI outbound guards and response metadata, without network traffic."""

import socket
from types import SimpleNamespace

import httpx
import pytest

from app.services import ai_service as ai


@pytest.mark.parametrize(
    "provider,url",
    [
        ("openai", None),
        ("unknown", "https://example.invalid"),
        ("openai", "https://example.invalid"),
        ("openai", ""),
    ],
)
def test_outbound_allowlist_rejects_untrusted_urls(provider, url):
    with pytest.raises(ai.AIProviderError):
        ai._check_outbound_url(provider, url)


@pytest.mark.parametrize(
    "answer",
    [
        [],
        [(None, None, None, None, ("not-an-ip",))],
        [(None, None, None, None, ("127.0.0.1",))],
    ],
)
def test_endpoint_resolution_rejects_empty_invalid_private_answers(monkeypatch, answer):
    monkeypatch.setattr(ai.socket, "getaddrinfo", lambda *args, **kwargs: answer)
    with pytest.raises(ai.AIProviderError):
        ai._resolve_public_endpoint("https://synthetic.invalid")


def test_dns_failure_is_controlled(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("synthetic DNS failure")

    monkeypatch.setattr(ai.socket, "getaddrinfo", fail)
    with pytest.raises(ai.AIProviderError, match="could not be resolved"):
        ai._resolve_public_endpoint("https://synthetic.invalid")


def test_ipv6_pinning_preserves_port_host_and_sni():
    url, names = ai._pin_public_endpoint(
        "https://synthetic.invalid:8443/v1/chat/completions", "2606:4700:4700::1111"
    )
    assert url == "https://[2606:4700:4700::1111]:8443/v1/chat/completions"
    assert names == {"host": "synthetic.invalid:8443", "sni": "synthetic.invalid"}


@pytest.mark.parametrize("info", [None, (), ("not-an-ip",)])
def test_unusable_peer_metadata_returns_none(info):
    class Stream:
        def get_extra_info(self, name):
            assert name == "server_addr"
            return info

    response = httpx.Response(200, extensions={"network_stream": Stream()})
    assert ai._response_peer_address(response) is None
    assert ai._response_peer_address(httpx.Response(200)) is None


@pytest.mark.parametrize(
    "provider,body",
    [
        ("anthropic", {"content": 42}),
        ("anthropic", {"content": [{"type": "tool_use"}]}),
        ("gemini", {}),
        ("gemini", {"candidates": []}),
        ("unknown", {}),
    ],
)
def test_missing_text_returns_empty(provider, body):
    assert ai.parse_response(provider, body) == ""


def test_invalid_anthropic_tool_list_returns_empty():
    assert ai._extract_tool_calls("anthropic", {"content": 42}) == []


@pytest.mark.parametrize(
    "provider,extra",
    [
        ("unknown", {}),
        ("cloudflare", {}),
        ("cloudflare", {"account_id": "bad"}),
        ("cloudflare_worker", {}),
    ],
)
def test_missing_provider_requirements_rejected(provider, extra):
    with pytest.raises(ValueError):
        ai.build_request(
            provider, "synthetic-key", "synthetic-model", "system", "user", **extra
        )


@pytest.mark.parametrize("failure", ["network", "not-json"])
def test_tool_loop_transport_errors_are_controlled(failure):
    def respond(request):
        if failure == "network":
            raise httpx.ConnectError("synthetic-key must stay private", request=request)
        return httpx.Response(200, text="not JSON")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ai.AIProviderError) as exc:
            ai.call_with_tools(
                "openai",
                "synthetic-key",
                "synthetic-model",
                "question",
                {},
                lambda *args, **kwargs: None,
                client=client,
            )
    assert "synthetic-key" not in str(exc.value)


def test_unknown_tool_provider_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        ai.call_with_tools(
            "unknown",
            "synthetic-key",
            "synthetic-model",
            "question",
            {},
            lambda *args, **kwargs: None,
        )


@pytest.mark.parametrize(
    "provider,peer",
    [("openai", None), ("custom", "93.184.216.34"), ("custom", "127.0.0.1")],
)
def test_production_request_branch_checks_peer_without_network(
    monkeypatch, provider, peer
):
    class Stream:
        def get_extra_info(self, name):
            return (peer, 443)

    def respond(request):
        if provider == "custom":
            assert request.url.host == "93.184.216.34"
            assert request.headers["host"] == "93.184.216.34"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Synthetic response"}}]},
            extensions={"network_stream": Stream()} if peer else {},
        )

    monkeypatch.setattr(
        ai,
        "_hardened_client",
        lambda timeout: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    monkeypatch.setattr(ai, "_resolve_public_endpoint", lambda url: "93.184.216.34")
    kwargs = (
        {"endpoint_url": "https://93.184.216.34/v1"} if provider == "custom" else {}
    )
    if peer == "127.0.0.1":
        with pytest.raises(ai.AIProviderError, match="private or local"):
            ai.call_provider(
                provider, "synthetic-key", "synthetic-model", "system", "user", **kwargs
            )
    else:
        assert (
            ai.call_provider(
                provider, "synthetic-key", "synthetic-model", "system", "user", **kwargs
            )
            == "Synthetic response"
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://[",
        "https:///",
        "https://bad..host",
        "https://.badhost",
        "https://93.184.216.34:0",
    ],
)
def test_malformed_config_urls_rejected_before_network(url):
    with pytest.raises(ValueError):
        ai.validate_worker_url(url)


def test_worker_url_dns_and_default_path_boundaries(monkeypatch):
    monkeypatch.setattr(
        ai.socket,
        "getaddrinfo",
        lambda *args: [(None, None, None, None, ("not-an-ip",))],
    )
    assert ai.validate_worker_url("https://public.example") == (
        "https://public.example/v1/chat/completions"
    )
    with pytest.raises(ValueError, match="invalid characters"):
        ai.validate_worker_url("https://bad%20host.example")
    monkeypatch.setattr(
        ai.socket,
        "getaddrinfo",
        lambda *args: [(None, None, None, None, ("127.0.0.1",))],
    )
    with pytest.raises(ValueError, match="resolves to a private"):
        ai.validate_worker_url("https://public.example/path")


def test_build_request_rejects_registered_but_unhandled_provider(monkeypatch):
    monkeypatch.setitem(
        ai.PROVIDERS,
        "synthetic",
        SimpleNamespace(wire_format="openai"),
    )
    with pytest.raises(ValueError, match="Unhandled AI provider"):
        ai.build_request("synthetic", "key", "model", "system", "user")


def test_tool_loop_wire_format_and_gemini_message_cleanup(monkeypatch):
    monkeypatch.setitem(
        ai.PROVIDERS,
        "synthetic",
        SimpleNamespace(wire_format="unsupported"),
    )
    with pytest.raises(ValueError, match="Tool calling not supported"):
        ai.call_with_tools("synthetic", "key", "model", "question", {}, lambda: None)

    original = ai.build_request

    def request_with_legacy_messages(*args, **kwargs):
        request = original(*args, **kwargs)
        request["json"]["messages"] = []
        return request

    monkeypatch.setattr(ai, "build_request", request_with_legacy_messages)

    def respond(request):
        assert "messages" not in request.read().decode()
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "done"}]}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = ai.call_with_tools(
            "gemini", "key", "model", "question", {}, lambda: None, client=client
        )
    assert result["final_response"] == "done"
