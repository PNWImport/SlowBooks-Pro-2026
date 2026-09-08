"""The database TLS guard must check the mode, not URL substrings."""

import pytest


@pytest.mark.parametrize("secret", ["", "   "])
@pytest.mark.parametrize("debug", [False, True])
def test_postgres_never_accepts_empty_encryption_secret(monkeypatch, secret, debug):
    import app.config as cfg
    import app.main as main

    monkeypatch.setattr(cfg, "DATABASE_URL", "postgresql://u:p@host/db?sslmode=require")
    monkeypatch.setattr(cfg, "PAYROLL_ENCRYPTION_SECRET", secret)
    monkeypatch.setattr(cfg, "APP_DEBUG", debug)
    monkeypatch.setattr(main, "FORCE_HTTPS", True)
    monkeypatch.setattr(main, "_create_missing_tables", lambda: None)
    with pytest.raises(RuntimeError, match="PAYROLL_ENCRYPTION_SECRET"):
        main._run_startup_security_checks()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@host/db?sslmode=disable",
        "postgresql://u:p@host/db?sslmode=prefer",
        "postgresql://u:p@host/db?sslmode=allow",
        "postgresql://u:ssl-password@host/db",
        "postgresql://u:p@host/ssl_database",
    ],
)
def test_production_rejects_optional_or_missing_tls(monkeypatch, url):
    import app.config as cfg
    import app.main as main

    monkeypatch.setattr(cfg, "DATABASE_URL", url)
    monkeypatch.setattr(cfg, "APP_DEBUG", False)
    monkeypatch.setattr(cfg, "PAYROLL_ENCRYPTION_SECRET", "test-unique-secret")
    monkeypatch.setattr(main, "FORCE_HTTPS", True)
    monkeypatch.delenv("SLOWBOOKS_PRIVATE_NETWORK", raising=False)
    monkeypatch.setattr(main, "_create_missing_tables", lambda: None)
    with pytest.raises(RuntimeError, match="TLS mode"):
        main._run_startup_security_checks()


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_production_accepts_required_tls(monkeypatch, mode):
    import app.config as cfg
    import app.main as main

    monkeypatch.setattr(cfg, "DATABASE_URL", f"postgresql://u:p@host/db?sslmode={mode}")
    monkeypatch.setattr(cfg, "APP_DEBUG", False)
    monkeypatch.setattr(cfg, "PAYROLL_ENCRYPTION_SECRET", "test-unique-secret")
    monkeypatch.setattr(main, "FORCE_HTTPS", True)
    monkeypatch.delenv("SLOWBOOKS_PRIVATE_NETWORK", raising=False)
    monkeypatch.setattr(main, "_create_missing_tables", lambda: None)
    main._run_startup_security_checks()
