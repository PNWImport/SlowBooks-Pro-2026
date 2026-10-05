"""Fail-closed launcher transport and Windows installer policy checks."""

from pathlib import Path
from unittest.mock import Mock

import pytest

import desktop_launcher as launcher


def test_real_tls_health_check_verifies_trust(tmp_path, monkeypatch):
    import shutil
    import ssl
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("openssl required for disposable TLS fixture")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("SLOWBOOKS_TLS_CERTFILE", str(cert))
    monkeypatch.setenv("SLOWBOOKS_TLS_KEYFILE", str(key))
    monkeypatch.setenv("SLOWBOOKS_TLS_CA_FILE", str(cert))
    monkeypatch.setenv("SLOWBOOKS_TLS_HEALTH_HOST", "localhost")
    monkeypatch.setattr(launcher, "get_env_value", lambda key: None)
    tls = launcher._lan_tls()

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/health" else 404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Health)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tls["ssl_certfile"], tls["ssl_keyfile"])
    server.socket = context.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    proc = Mock()
    proc.poll.return_value = None
    try:
        assert launcher.wait_for_health(proc, server.server_port, timeout=2, tls=True)
        monkeypatch.delenv("SLOWBOOKS_TLS_CA_FILE")
        assert not launcher.wait_for_health(
            proc, server.server_port, timeout=0.1, tls=True
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_lan_without_certificates_does_not_spawn(monkeypatch):
    monkeypatch.delenv("SLOWBOOKS_TLS_CERTFILE", raising=False)
    monkeypatch.delenv("SLOWBOOKS_TLS_KEYFILE", raising=False)
    monkeypatch.setattr(launcher, "get_env_value", lambda key: None)
    spawn = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    with pytest.raises(RuntimeError, match="requires SLOWBOOKS_TLS"):
        launcher.start_server("sqlite:///synthetic.db", 3001, bind_host="0.0.0.0")
    spawn.assert_not_called()


def test_lan_child_uses_tls_and_production_guards(monkeypatch):
    monkeypatch.setattr(launcher, "FROZEN", False)
    monkeypatch.setattr(
        launcher,
        "_lan_tls",
        lambda: {"ssl_certfile": "/cert.pem", "ssl_keyfile": "/key.pem"},
    )
    monkeypatch.setenv("SLOWBOOKS_PRIVATE_NETWORK", "1")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    spawn = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    launcher.start_server("sqlite:///synthetic.db", 3001, bind_host="0.0.0.0")
    command = spawn.call_args.args[0]
    env = spawn.call_args.kwargs["env"]
    assert "--ssl-certfile" in command
    assert "--ssl-keyfile" in command
    assert "--no-proxy-headers" in command
    assert env["APP_DEBUG"] == "false"
    assert env["FORCE_HTTPS"] == "true"
    assert env["SLOWBOOKS_PRIVATE_NETWORK"] == "0"
    assert env["FORWARDED_ALLOW_IPS"] == ""


def test_desktop_remains_loopback_http(monkeypatch):
    tls = Mock(side_effect=AssertionError("desktop must not require TLS"))
    monkeypatch.setattr(launcher, "_lan_tls", tls)
    monkeypatch.setattr(launcher, "FROZEN", False)
    spawn = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    launcher.start_server("sqlite:///synthetic.db", 3001)
    assert spawn.call_args.kwargs["env"]["FORCE_HTTPS"] == "false"
    tls.assert_not_called()


def test_windows_installer_restricts_privileges_and_firewall():
    source = (
        Path(__file__).parents[1] / "scripts/windows/serveredition-install.ps1"
    ).read_text(encoding="utf-8")
    assert "/RU SYSTEM" not in source
    assert "/RL HIGHEST" not in source
    assert "/RU 'NT AUTHORITY\\LOCALSERVICE' /RL LIMITED" in source
    assert "profile=private,domain remoteip=localsubnet" in source
    assert 'program="$ExePath"' in source
    assert source.index("foreach ($ItemName") < source.index("Copy-Item")
    assert 'Write-Host "Plain HTTP' not in source


def test_windows_updater_checks_https_without_bypassing_trust():
    source = (
        Path(__file__).parents[1] / "scripts/windows/update-server-edition.ps1"
    ).read_text(encoding="utf-8")
    assert '"https://${HealthHost}:$Port/health"' in source
    assert '"http://127.0.0.1:$Port/health"' not in source
    assert "SkipCertificateCheck" not in source
