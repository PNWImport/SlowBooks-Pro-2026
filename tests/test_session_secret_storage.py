"""Session key persistence must survive restarts without exposing the key."""

import logging
import os
import stat

import pytest

from app.services import auth


@pytest.fixture
def key_path(tmp_path, monkeypatch):
    monkeypatch.delenv("SESSION_SECRET_KEY", raising=False)
    monkeypatch.setattr(auth, "__file__", str(tmp_path / "app/services/auth.py"))
    return tmp_path / ".slowbooks-session.key"


def test_environment_key_takes_precedence(key_path, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET_KEY", "  synthetic-environment-key  ")
    assert auth.get_session_secret() == "synthetic-environment-key"
    assert not key_path.exists()


@pytest.mark.parametrize("initial", [None, "", "   \n"])
def test_generated_key_is_private_and_stable(key_path, initial, caplog):
    if initial is not None:
        key_path.write_text(initial)
    with caplog.at_level(logging.INFO, logger=auth.__name__):
        first = auth.get_session_secret()
        second = auth.get_session_secret()
    assert len(first) >= 48
    assert first == second == key_path.read_text(encoding="utf-8")
    if os.name == "posix":  # Windows has no owner-only mode bits
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert first not in caplog.text
    assert not list(key_path.parent.glob(".session-key-*"))


def test_existing_key_is_preserved(key_path):
    key_path.write_text("  synthetic-existing-key\n")
    assert auth.get_session_secret() == "synthetic-existing-key"
    assert key_path.read_text(encoding="utf-8") == "  synthetic-existing-key\n"


def test_read_only_storage_warns_without_disclosing_key(key_path, monkeypatch, caplog):
    import tempfile

    def denied(**kwargs):
        raise PermissionError("synthetic read-only filesystem")

    monkeypatch.setattr(tempfile, "mkstemp", denied)
    with caplog.at_level(logging.WARNING, logger=auth.__name__):
        secret = auth.get_session_secret()
    assert len(secret) >= 48
    assert not key_path.exists()
    assert "NOT persisted" in caplog.text
    assert secret not in caplog.text


def test_failed_atomic_replace_does_not_leave_secret_copy(key_path, monkeypatch):
    def denied(*args):
        raise PermissionError("synthetic replace failure")

    monkeypatch.setattr(auth.os, "replace", denied)
    assert len(auth.get_session_secret()) >= 48
    assert not key_path.exists()
    assert list(key_path.parent.glob(".session-key-*")) == []


def test_unreadable_key_fallback_is_reported(key_path, monkeypatch, caplog):
    from pathlib import Path

    key_path.write_text("synthetic-existing")
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path == key_path:
            raise PermissionError("synthetic read failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    secret = auth.get_session_secret()
    assert len(secret) >= 48
    assert "could not read" in caplog.text
    assert "NOT persisted" in caplog.text
    assert secret not in caplog.text


def test_cleanup_failure_is_reported_without_logging_secret(
    key_path, monkeypatch, caplog
):
    def denied(*args):
        raise PermissionError("synthetic storage failure")

    with monkeypatch.context() as patch:
        patch.setattr(auth.os, "replace", denied)
        patch.setattr(auth.os, "unlink", denied)
        secret = auth.get_session_secret()
    assert "could not remove temporary session key" in caplog.text
    assert secret not in caplog.text
    # Remove only this test's synthetic secret after the simulated fault ends.
    for temporary in key_path.parent.glob(".session-key-*"):
        temporary.unlink()
