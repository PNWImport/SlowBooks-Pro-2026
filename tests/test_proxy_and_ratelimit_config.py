"""Two config gaps that silently weaken security behind a reverse proxy.

Both were live in docker-compose.prod.yml, which explicitly puts the app
behind a TLS-terminating proxy:

1. FORWARDED_ALLOW_IPS unset. uvicorn parses X-Forwarded-For but trusts
   it only from `forwarded_allow_ips` (default 127.0.0.1). A proxy in
   another container has a different address, so every request reports
   the proxy's IP — collapsing the login rate limiter into one shared
   bucket and writing the proxy address into login_attempts and
   portal_accesses.

2. RATE_LIMIT_STORAGE_URI unset with multiple workers. slowapi's default
   MemoryStorage is per-process, so the configured limit is multiplied by the
   worker count. Compose now defaults to one worker.

Explicit overrides still warn rather than refuse. These tests pin the safe
Compose default, warnings, and storage wiring.
"""

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_prod_compose_requires_forwarded_allow_ips():
    """Compose must refuse to start without it, like the other secrets."""
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text())
    value = compose["services"]["slowbooks"]["environment"]["FORWARDED_ALLOW_IPS"]
    assert value.startswith("${FORWARDED_ALLOW_IPS:?"), (
        "docker-compose.prod.yml must hard-require FORWARDED_ALLOW_IPS — it "
        "puts the app behind a proxy, which makes client IPs wrong without it"
    )


@pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_exposes_rate_limit_storage(compose):
    text = (ROOT / compose).read_text()
    assert "RATE_LIMIT_STORAGE_URI" in text


@pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_defaults_to_one_worker_without_shared_rate_limits(compose):
    text = (ROOT / compose).read_text()
    assert 'APP_WORKERS: "${APP_WORKERS:-1}"' in text


def test_limiter_defaults_to_memory_storage(monkeypatch):
    """Unset URI keeps today's behaviour — single-container dev is fine."""
    monkeypatch.delenv("RATE_LIMIT_STORAGE_URI", raising=False)
    import app.services.rate_limit as rl

    importlib.reload(rl)
    assert rl.RATE_LIMIT_STORAGE_URI == ""
    assert type(rl.limiter._storage).__name__ == "MemoryStorage"


def test_limiter_honours_storage_uri(monkeypatch):
    """A configured URI is passed through to slowapi, not ignored."""
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "memory://custom")
    import app.services.rate_limit as rl

    importlib.reload(rl)
    try:
        assert rl.RATE_LIMIT_STORAGE_URI == "memory://custom"
        assert rl.limiter._storage_uri == "memory://custom"
    finally:
        monkeypatch.delenv("RATE_LIMIT_STORAGE_URI", raising=False)
        importlib.reload(rl)


def test_limiter_builds_redis_storage_when_configured(monkeypatch):
    """The production image must include Redis' Python client for shared limits."""
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "redis://redis:6379/0")
    import app.services.rate_limit as rl

    importlib.reload(rl)
    try:
        assert type(rl.limiter._storage).__name__ == "RedisStorage"
    finally:
        monkeypatch.delenv("RATE_LIMIT_STORAGE_URI", raising=False)
        importlib.reload(rl)


def test_warns_when_proxy_trust_unset(monkeypatch, caplog):
    import app.main as main

    monkeypatch.setattr(main, "FORCE_HTTPS", True)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)

    with caplog.at_level("WARNING", logger="uvicorn.error"):
        main._warn_on_proxy_misconfiguration()

    assert any("FORWARDED_ALLOW_IPS" in r.message for r in caplog.records)


def test_no_proxy_warning_when_trust_configured(monkeypatch, caplog):
    import app.main as main

    monkeypatch.setattr(main, "FORCE_HTTPS", True)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.18.0.0/16")

    with caplog.at_level("WARNING", logger="uvicorn.error"):
        main._warn_on_proxy_misconfiguration()

    assert not any("FORWARDED_ALLOW_IPS" in r.message for r in caplog.records)


def test_warns_on_multiworker_memory_rate_limit(monkeypatch, caplog):
    import app.main as main
    import app.services.rate_limit as rl

    monkeypatch.setattr(main, "FORCE_HTTPS", False)
    monkeypatch.setenv("APP_WORKERS", "4")
    monkeypatch.setattr(rl, "RATE_LIMIT_STORAGE_URI", "")
    monkeypatch.setattr(rl, "_enabled", True)

    with caplog.at_level("WARNING", logger="uvicorn.error"):
        main._warn_on_proxy_misconfiguration()

    assert any("RATE_LIMIT_STORAGE_URI" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    "workers,storage,expected",
    [
        ("1", "", False),  # single worker — memory storage is correct
        ("4", "redis://r:6379/0", False),  # shared storage — fine at any count
        ("4", "", True),  # the broken combination
    ],
)
def test_rate_limit_warning_matrix(monkeypatch, caplog, workers, storage, expected):
    import app.main as main
    import app.services.rate_limit as rl

    monkeypatch.setattr(main, "FORCE_HTTPS", False)
    monkeypatch.setenv("APP_WORKERS", workers)
    monkeypatch.setattr(rl, "RATE_LIMIT_STORAGE_URI", storage)
    monkeypatch.setattr(rl, "_enabled", True)

    with caplog.at_level("WARNING", logger="uvicorn.error"):
        main._warn_on_proxy_misconfiguration()

    warned = any("RATE_LIMIT_STORAGE_URI" in r.message for r in caplog.records)
    assert warned is expected
