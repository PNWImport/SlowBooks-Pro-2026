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
    text = (ROOT / compose_name).read_text()
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
    text = (ROOT / "docker-entrypoint.sh").read_text()
    assert "--host 0.0.0.0" not in text, (
        "docker-entrypoint.sh hardcodes --host, so APP_HOST is ignored: "
        "setting it in .env or compose changes nothing and warns nobody"
    )
    assert "APP_HOST:-0.0.0.0" in text, (
        "entrypoint should read APP_HOST, defaulting to 0.0.0.0 — which is "
        "correct INSIDE a container"
    )


def test_dockerignore_excludes_secrets_and_history():
    """Anything listed here cannot be baked into an image layer."""
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    for required in (".env", ".git"):
        assert required in ignored, f".dockerignore must exclude {required}"


def test_container_runs_as_non_root():
    text = (ROOT / "Dockerfile").read_text()
    users = re.findall(r"^\s*USER\s+(\S+)", text, re.M)
    assert users, "Dockerfile has no USER directive — the container runs as root"
    assert users[-1] != "root", f"Dockerfile's final USER is {users[-1]}"


@pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_does_not_hardcode_a_password(compose):
    """Credentials come from the environment, never from the file."""
    text = (ROOT / compose).read_text()
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        m = re.search(r"(PASSWORD|SECRET|TOKEN)\s*:\s*(.+)$", line)
        # A value is safe when every credential in it comes from the
        # environment. DATABASE_URL embeds ${VAR} mid-string, so testing
        # only the first character misses it.
        if m and "${" not in m.group(2):
            pytest.fail(f"{compose}:{i} hardcodes a credential: {line.strip()[:80]}")
