"""Settings-secret key lifecycle and defensive API boundaries."""

import os

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.services import crypto


def _reset(monkeypatch, key_file, env_key=None):
    monkeypatch.setattr(crypto, "_KEY_FILE", key_file)
    if env_key is None:
        monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)
    else:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", env_key)
    crypto.reset_cache_for_tests()


def test_master_key_prefers_environment_and_existing_file(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path / "unused", Fernet.generate_key().decode())
    assert (
        crypto._load_or_create_master_key()
        == os.environ["SETTINGS_ENCRYPTION_KEY"].encode()
    )

    stored = Fernet.generate_key()
    key_file = tmp_path / "existing.key"
    key_file.write_bytes(stored + b"\n")
    _reset(monkeypatch, key_file)
    assert crypto._load_or_create_master_key() == stored


def test_master_key_creation_fallback_and_hard_failure(monkeypatch, tmp_path):
    key_file = tmp_path / "created.key"
    _reset(monkeypatch, key_file)
    created = crypto._load_or_create_master_key()
    assert key_file.read_bytes() == created
    if os.name == "posix":  # Windows has no owner-only mode bits
        assert key_file.stat().st_mode & 0o777 == 0o600

    fallback = tmp_path / "fallback.key"
    _reset(monkeypatch, fallback)
    monkeypatch.setattr(
        "tempfile.mkstemp",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("no atomic")),
    )
    fallback_key = crypto._load_or_create_master_key()
    assert fallback.read_bytes() == fallback_key
    if os.name == "posix":
        assert fallback.stat().st_mode & 0o777 == 0o600

    _reset(monkeypatch, tmp_path / "missing" / "key")
    with pytest.raises(RuntimeError, match="refusing to use an ephemeral key"):
        crypto._load_or_create_master_key()


def test_crypto_public_api_handles_empty_plaintext_and_invalid_ciphertext(
    monkeypatch, tmp_path
):
    _reset(monkeypatch, tmp_path / "key", Fernet.generate_key().decode())
    assert crypto.encrypt_value(None) == ""
    assert crypto.encrypt_value("") == ""
    encrypted = crypto.encrypt_value("top-secret")
    assert crypto.decrypt_value(encrypted) == "top-secret"
    assert crypto.decrypt_value(None) == ""
    assert crypto.decrypt_value("") == ""
    assert crypto.decrypt_value("legacy plaintext") == "legacy plaintext"
    with pytest.raises(InvalidToken):
        crypto.decrypt_value(crypto.CIPHERTEXT_PREFIX + "not-a-token")
    assert crypto.is_encrypted(encrypted) is True
    assert crypto.is_encrypted("") is False
    assert crypto.mask_secret("") == ""
    assert crypto.mask_secret("abc") == "••••••••"
    assert crypto.mask_secret("abcdefghij") == "••••••••ghij"
