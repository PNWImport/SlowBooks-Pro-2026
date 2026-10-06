"""Company discovery and failure recovery, isolated from real company files."""

from datetime import datetime
from pathlib import Path

import pytest

from app.models.companies import Company
from app.services import company_service as service


@pytest.fixture
def desktop(monkeypatch, tmp_path):
    monkeypatch.setenv("SLOWBOOKS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        service, "DATABASE_URL", f"sqlite:///{tmp_path}/companies/live.db"
    )
    monkeypatch.setattr(service, "_warned_missing_manifest", False)
    return tmp_path


@pytest.mark.parametrize("filename", ["live.db\n", "live.db\r", "live.db\r\n"])
def test_company_paths_reject_trailing_line_breaks(desktop, filename):
    assert service.safe_company_filename(filename) is None
    assert service.company_db_path(filename) is None


@pytest.mark.parametrize("contents", ["{", "[]", "null"])
def test_invalid_manifest_falls_back_without_overwriting_file(desktop, contents):
    path = service.manifest_path()
    path.write_text(contents, encoding="utf-8")
    assert service._read_manifest() == {"companies": [], "last_opened": None}
    assert path.read_text(encoding="utf-8") == contents


def test_failed_creation_cleans_partial_database_preserves_manifest(
    desktop, monkeypatch
):
    manifest = {
        "companies": [{"name": "Live", "file": "live.db"}],
        "last_opened": "live.db",
    }
    service._write_manifest(manifest)

    def fail(url):
        Path(url.removeprefix("sqlite:///")).write_bytes(b"partial migration")
        raise RuntimeError("private database details")

    monkeypatch.setattr(service, "_init_company_db", fail)
    result = service.manifest_create_company("New")
    assert result["success"] is False
    assert "private" not in result["error"]
    assert not (service.companies_dir() / "new.db").exists()
    assert service._read_manifest() == manifest


def test_manifest_lookup_and_reconciliation_failure(desktop, monkeypatch, db_session):
    service._write_manifest({"companies": [{"name": "Live", "file": "live.db"}]})
    assert service.warn_if_manifest_missing() is None
    assert service.company_db_path("../escape.db") is None
    assert service.company_db_path("live.db") == service.companies_dir() / "live.db"
    assert service.company_name_taken_by(" ") is None
    assert service.company_name_taken_by("LIVE!") == "live.db"

    def fail(*args):
        raise RuntimeError("unavailable setting")

    monkeypatch.setattr(service, "sync_manifest_name", fail)
    assert service.list_companies(db_session) == [
        {"name": "Live", "file": "live.db", "is_current": True}
    ]


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///", "sqlite:///:memory:"])
def test_no_file_url_cannot_rename_manifest(url, desktop, monkeypatch):
    monkeypatch.setattr(service, "DATABASE_URL", url)
    assert service._current_company_file() is None
    assert service.sync_manifest_name("New") is False


def test_registered_postgres_company_list_does_not_duplicate_current(
    monkeypatch, db_session
):
    monkeypatch.setattr(service, "DATABASE_URL", "postgresql://test@host/live")
    db_session.add_all(
        [
            Company(
                name="Live", database_name="live", last_accessed=datetime(2026, 1, 2)
            ),
            Company(name="Other", database_name="other"),
            Company(name="Hidden", database_name="hidden", is_active=False),
        ]
    )
    db_session.commit()
    rows = service.list_companies(db_session)
    assert [(r["database_name"], r["is_current"]) for r in rows] == [
        ("live", True),
        ("other", False),
    ]
    assert rows[0]["last_accessed"] == "2026-01-02T00:00:00"
    assert service.sync_manifest_name("New") is False
    assert service.company_name_taken_by("Live") is None
    assert service.warn_if_manifest_missing() is None
    assert service.get_company_db_url("other") == "postgresql://test@host/other"


def test_postgres_creation_rejections_do_not_contact_server(monkeypatch, db_session):
    monkeypatch.setattr(service, "DATABASE_URL", "postgresql://test@host/live")
    db_session.add(Company(name="Other", database_name="other"))
    db_session.commit()

    def unexpected(*args, **kwargs):
        pytest.fail("Rejected creation contacted the database server")

    monkeypatch.setattr(service, "create_engine", unexpected)
    assert service.create_company(db_session, "Other")["success"] is False
    assert (
        "already exists"
        in service.create_company(db_session, "Other", "other")["error"]
    )


def test_postgres_connection_failure_is_reported_without_registering(
    monkeypatch, db_session
):
    monkeypatch.setattr(service, "DATABASE_URL", "postgresql://test@host/live")

    def fail(*args, **kwargs):
        raise RuntimeError("private connection details")

    monkeypatch.setattr(service, "create_engine", fail)
    result = service.create_company(db_session, "New", "new")
    assert result["success"] is False
    assert "private" not in result["error"]
    assert db_session.query(Company).count() == 0


def test_windows_data_directory_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("SLOWBOOKS_DATA_DIR", raising=False)
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert service.data_dir() == tmp_path / "SlowBooksPro" / "data"


@pytest.mark.parametrize("url", ["sqlite:///:memory:", "invalid-without-a-path"])
def test_current_postgres_name_absent_for_non_postgres_urls(monkeypatch, url):
    monkeypatch.setattr(service, "DATABASE_URL", url)
    assert service._current_database_name() is None


@pytest.mark.parametrize("filename", ["../escape.db", "../companies-other/escape.db"])
def test_secondary_containment_guard_survives_a_broken_slugger(
    desktop, monkeypatch, filename
):
    # Fault injection: normal slug generation cannot return these paths.
    # Verify the independent guard still prevents database initialization.
    monkeypatch.setattr(service, "company_filename_for", lambda name: filename)

    def unexpected_init(url):
        pytest.fail("Out-of-directory company path reached initialization")

    monkeypatch.setattr(service, "_init_company_db", unexpected_init)
    assert service.manifest_create_company("New") == {
        "success": False,
        "error": "Invalid company file name",
    }
    assert not service.companies_dir().exists()
    assert not service.manifest_path().exists()
