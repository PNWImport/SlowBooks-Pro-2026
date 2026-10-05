"""Docker must not publish the app or the database to every interface.

A Docker port mapping written as "3001:3001" binds 0.0.0.0 on the HOST.
`docker compose up` then hands the payroll app — and, worse, Postgres — to
every network the machine is attached to. It is a one-token difference from
"127.0.0.1:3001:3001" and invisible in `docker ps` output unless you look
for the missing address.

The bind address INSIDE the container is a separate question with the
opposite answer: 0.0.0.0 is required there, because binding 127.0.0.1
inside the container makes it unreachable even through Docker's own port
forwarding. These tests keep the two from being conflated.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_build_context_excludes_local_secrets_and_customer_data():
    patterns = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    assert {
        "**/.env*",
        "**/.slowbooks-*.key",
        "**/slowbooks-settings-master.key",
        "certs/",
        "**/*.db",
        "**/*.db-*",
        "**/*.sqlite",
        "**/*.sqlite-*",
        "**/*.sqlite3",
        "**/*.sqlite3-*",
        "**/*.log",
        "**/*.pid",
        "app/static/uploads/",
    } <= patterns


def test_runtime_image_removes_pip_module_and_launchers():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for runtime_only_path in (
        "/usr/local/bin/pip",
        "/usr/local/bin/pip3",
        "/usr/local/bin/pip3.13",
        "/usr/local/lib/python3.13/site-packages/pip",
        "/usr/local/lib/python3.13/ensurepip",
    ):
        assert runtime_only_path in dockerfile


def test_gitignore_excludes_local_secrets_and_runtime_state():
    patterns = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert {
        ".env",
        ".env.*",
        "!.env.example",
        ".slowbooks-master.key",
        ".slowbooks-session.key",
        "slowbooks-settings-master.key",
        "certs/",
        "*.db-*",
        "*.sqlite-*",
        "*.sqlite3-*",
        "*.log",
        "*.pid",
    } <= patterns


@pytest.mark.parametrize(
    "compose_name",
    [
        "docker-compose.yml",
        "docker-compose.prod.yml",
    ],
)
def test_compose_passes_required_secrets_to_app(compose_name):
    import yaml

    compose = yaml.safe_load((ROOT / compose_name).read_text(encoding="utf-8"))
    env = compose["services"]["slowbooks"]["environment"]
    # PII encryption must fail loudly when unset; the session key is
    # auto-persisted and the settings key derived from the payroll secret
    # when left empty (see the comments beside them), but both are always
    # forwarded so a value set in .env reaches the container.
    assert env["PAYROLL_ENCRYPTION_SECRET"].startswith("${PAYROLL_ENCRYPTION_SECRET:?")
    assert "SESSION_SECRET_KEY" in env
    assert "SETTINGS_ENCRYPTION_KEY" in env

    assert "AUDIT_CHECKPOINT_SIGNING_SECRET" in env
    assert "AUDIT_CHECKPOINT_KEY_ID" in env
    if compose_name == "docker-compose.prod.yml":
        assert env["AUDIT_CHECKPOINT_SIGNING_SECRET"].startswith(
            "${AUDIT_CHECKPOINT_SIGNING_SECRET:?"
        )
        assert env["AUDIT_CHECKPOINT_KEY_ID"].startswith("${AUDIT_CHECKPOINT_KEY_ID:?")


def test_docker_healthcheck_accepts_direct_health_and_https_redirect(monkeypatch):
    import urllib.error

    from scripts import docker_healthcheck

    class _Response:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class _Opener:
        def __init__(self, result):
            self.result = result

        def open(self, _url, timeout):
            assert timeout == 3
            if isinstance(self.result, Exception):
                raise self.result
            return _Response(self.result)

    for result, expected in (
        (200, 0),
        (urllib.error.HTTPError("http://test", 308, "redirect", {}, None), 0),
        (503, 1),
        (urllib.error.URLError("offline"), 1),
    ):
        monkeypatch.setattr(
            docker_healthcheck.urllib.request,
            "build_opener",
            lambda *_args, result=result: _Opener(result),
        )
        assert docker_healthcheck.probe("http://127.0.0.1:3001/health") == expected


@pytest.mark.parametrize("status, expected", [(200, 0), (308, 0), (503, 1)])
def test_docker_healthcheck_against_real_http_server(status, expected):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from scripts import docker_healthcheck

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            if status == 308:
                # Nothing listens here. Following this redirect would make the
                # probe fail, which is the production-container regression.
                self.send_header("Location", "https://127.0.0.1:1/health")
            self.end_headers()

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/health"
        assert docker_healthcheck.probe(url) == expected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


# "[host_addr:]host_port:container_port", quotes optional.
PORT_LINE = re.compile(r'^\s*-\s*"?([^"\n]+?)"?\s*$')


def _split_outside_braces(spec: str) -> list[str]:
    """Split on ':' but not inside ${...}.

    A naive split breaks "${BIND_ADDR:-127.0.0.1}" apart at the ':-',
    which makes the host address unreadable — the bug this helper exists
    to avoid.
    """
    parts, buf, depth = [], "", 0
    for ch in spec:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch == ":" and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return parts


def _published_ports(compose_name: str) -> list[str]:
    """Every `ports:` entry in a compose file, as written."""
    text = (ROOT / compose_name).read_text(encoding="utf-8")
    out, in_ports = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.match(r"^\s*ports:\s*$", line):
            in_ports = True
            continue
        if in_ports:
            m = PORT_LINE.match(line)
            if m and ":" in m.group(1):
                out.append(m.group(1))
            elif stripped and not stripped.startswith("-"):
                in_ports = False
    return out


def test_dev_compose_publishes_only_to_loopback():
    """Any published port must name a host address, and it must not be
    a wildcard by default."""
    offenders = []
    for spec in _published_ports("docker-compose.yml"):
        parts = _split_outside_braces(spec)
        # "3001:3001" -> 2 parts, no host address == binds 0.0.0.0
        if len(parts) < 3:
            offenders.append(f"{spec} (no host address — binds all interfaces)")
            continue
        host_addr = parts[0]
        if "BIND_ADDR" in host_addr:
            # Templated: the DEFAULT is what ships, so check it.
            default = re.search(r"\$\{BIND_ADDR:-([^}]+)\}", host_addr)
            assert default, f"{spec}: BIND_ADDR has no default"
            if default.group(1) not in ("127.0.0.1", "localhost"):
                offenders.append(f"{spec} (default {default.group(1)} is not loopback)")
        elif host_addr not in ("127.0.0.1", "localhost"):
            offenders.append(f"{spec} (host address {host_addr} is not loopback)")
    assert (
        not offenders
    ), "docker-compose.yml publishes to non-loopback addresses:\n  " + "\n  ".join(
        offenders
    )


def test_prod_compose_publishes_nothing():
    """Production sits behind a TLS proxy; nothing should reach the host
    directly, including postgres."""
    assert not _published_ports("docker-compose.prod.yml"), (
        "docker-compose.prod.yml publishes ports to the host. Production is "
        "documented as sitting behind a reverse proxy — use `expose:` instead."
    )


def test_entrypoint_honors_app_host():
    """A config knob that silently does nothing is worse than no knob."""
    text = (ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "--host 0.0.0.0" not in text, (
        "docker-entrypoint.sh hardcodes --host, so APP_HOST is ignored: "
        "setting it in .env or compose changes nothing and warns nobody"
    )
    assert "APP_HOST:-0.0.0.0" in text, (
        "entrypoint should read APP_HOST, defaulting to 0.0.0.0 — which is "
        "correct INSIDE a container"
    )
    assert "APP_WORKERS:-1" in text


def test_native_default_is_loopback_while_containers_bind_internally():
    """Native installs should not join the LAN by copying `.env.example`.

    Docker and explicit Server Edition launches override this value because
    their own exposure controls live outside the application process.
    """
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert 'os.getenv("APP_HOST", "127.0.0.1")' in config
    assert re.search(r"^APP_HOST=127\.0\.0\.1$", env_example, re.MULTILINE)

    import yaml

    for compose_name in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = yaml.safe_load((ROOT / compose_name).read_text(encoding="utf-8"))
        assert compose["services"]["slowbooks"]["environment"]["APP_HOST"] == (
            "0.0.0.0"
        )


def test_dockerignore_excludes_secrets_and_history():
    """Anything listed here cannot be baked into an image layer."""
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    for required in (".env", ".git"):
        assert required in ignored, f".dockerignore must exclude {required}"


@pytest.mark.parametrize(
    "compose_name", ["docker-compose.yml", "docker-compose.prod.yml"]
)
def test_app_container_is_runtime_hardened(compose_name):
    import yaml

    app = yaml.safe_load((ROOT / compose_name).read_text(encoding="utf-8"))["services"][
        "slowbooks"
    ]
    assert app["read_only"] is True
    assert app["init"] is True
    assert app["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in app["security_opt"]


@pytest.mark.parametrize(
    "compose_name", ["docker-compose.yml", "docker-compose.prod.yml"]
)
def test_compose_prepares_writable_data_volumes_without_privileging_app(compose_name):
    import yaml

    compose = yaml.safe_load((ROOT / compose_name).read_text(encoding="utf-8"))
    init = compose["services"]["storage-init"]
    app = compose["services"]["slowbooks"]

    assert init["user"] == "0:0"
    assert init["network_mode"] == "none"
    assert init["read_only"] is True
    assert init["cap_drop"] == ["ALL"]
    assert init["cap_add"] == ["CHOWN"]
    assert "no-new-privileges:true" in init["security_opt"]
    assert init["entrypoint"] == [
        "chown",
        "-R",
        "1000:1000",
        "/app/backups",
        "/app/app/static/uploads",
    ]
    assert set(init["volumes"]) == set(app["volumes"])
    assert app["depends_on"]["storage-init"]["condition"] == (
        "service_completed_successfully"
    )
    assert any(str(item).startswith("/tmp:") for item in app["tmpfs"])


def test_container_runs_as_non_root():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    users = re.findall(r"^\s*USER\s+(\S+)", text, re.M)
    assert users, "Dockerfile has no USER directive — the container runs as root"
    assert users[-1] != "root", f"Dockerfile's final USER is {users[-1]}"


@pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_does_not_hardcode_a_password(compose):
    """Credentials come from the environment, never from the file."""
    text = (ROOT / compose).read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        m = re.search(r"(PASSWORD|SECRET|TOKEN)\s*:\s*(.+)$", line)
        # A value is safe when every credential in it comes from the
        # environment. DATABASE_URL embeds ${VAR} mid-string, so testing
        # only the first character misses it.
        if m and "${" not in m.group(2):
            pytest.fail(f"{compose}:{i} hardcodes a credential: {line.strip()[:80]}")
