from fastapi import Request

from app.services.request_utils import client_ip


def _request(headers=(), client=("198.51.100.7", 1234)):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
            "client": client,
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


def test_client_ip_uses_peer_without_trusted_proxy(monkeypatch):
    monkeypatch.setattr("app.config.TRUST_PROXY_HEADERS", False)
    assert client_ip(_request([("x-forwarded-for", "203.0.113.9")])) == "198.51.100.7"


def test_client_ip_uses_first_forwarded_hop_and_truncates(monkeypatch):
    monkeypatch.setattr("app.config.TRUST_PROXY_HEADERS", True)
    forwarded = "203.0.113.9, 198.51.100.1"
    assert client_ip(_request([("x-forwarded-for", forwarded)])) == "203.0.113.9"
    assert len(client_ip(_request([("x-forwarded-for", "a" * 100)]))) == 45


def test_client_ip_handles_missing_peer(monkeypatch):
    monkeypatch.setattr("app.config.TRUST_PROXY_HEADERS", False)
    assert client_ip(_request(client=None)) == ""
