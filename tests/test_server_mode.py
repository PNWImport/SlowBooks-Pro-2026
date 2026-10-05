"""Server Edition groundwork (PR-S1): LAN bind plumbing, SQLite WAL
tuning, and the /api/system server_mode flag the UI keys its header off."""

import sqlite3
import sys

import pytest
from sqlalchemy import create_engine, text

import desktop_launcher
from app.database import enable_sqlite_tuning

# ---------------------------------------------------------------------------
# SQLite concurrency tuning
# ---------------------------------------------------------------------------


def test_sqlite_tuning_enables_wal(tmp_path):
    db = tmp_path / "tuned.db"
    engine = create_engine(f"sqlite:///{db}")
    enable_sqlite_tuning(engine)
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        busy = conn.execute(text("PRAGMA busy_timeout")).scalar()
        sync = conn.execute(text("PRAGMA synchronous")).scalar()
    assert str(mode).lower() == "wal"
    assert int(busy) == 5000
    assert int(sync) == 1  # NORMAL

    # WAL is persistent in the file: a plain sqlite3 connection sees it too
    raw = sqlite3.connect(db)
    assert raw.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    raw.close()


def test_sqlite_tuning_harmless_on_memory_db():
    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_tuning(engine)
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert str(mode).lower() == "memory"  # no-op, no error


# ---------------------------------------------------------------------------
# Launcher bind plumbing
# ---------------------------------------------------------------------------


def test_server_env_default_is_loopback():
    env = desktop_launcher._server_env("sqlite:///x.db", 3001)
    assert env["APP_HOST"] == "127.0.0.1"
    assert env["SLOWBOOKS_SERVER_MODE"] == "0"


def test_server_env_lan_bind_sets_server_mode():
    env = desktop_launcher._server_env("sqlite:///x.db", 3001, bind_host="0.0.0.0")
    assert env["APP_HOST"] == "0.0.0.0"
    assert env["SLOWBOOKS_SERVER_MODE"] == "1"
    assert env["APP_DEBUG"] == "false"
    assert env["FORCE_HTTPS"] == "true"
    env = desktop_launcher._server_env(
        "sqlite:///x.db", 3001, bind_host="192.168.68.50"
    )
    assert env["SLOWBOOKS_SERVER_MODE"] == "1"


def test_lan_addresses_never_raises():
    addrs = desktop_launcher._lan_addresses()
    assert isinstance(addrs, list)
    assert all(isinstance(a, str) and a for a in addrs)


# ---------------------------------------------------------------------------
# /api/system flag
# ---------------------------------------------------------------------------


def test_system_info_reports_server_mode(authed_client, monkeypatch):
    info = authed_client.get("/api/system").json()
    assert info["server_mode"] is False

    monkeypatch.setenv("SLOWBOOKS_SERVER_MODE", "1")
    info = authed_client.get("/api/system").json()
    assert info["server_mode"] is True


# ---------------------------------------------------------------------------
# PR-S4: banner composition + --data-dir override
# ---------------------------------------------------------------------------


def test_serve_banner_lists_all_addresses():
    text = desktop_launcher._compose_serve_banner(3001, ["OFFICE-PC", "192.168.68.50"])
    assert "https://OFFICE-PC:3001" in text
    assert "https://192.168.68.50:3001" in text
    assert "HTTPS is required" in text
    # No addresses discovered: still renders something actionable
    fallback = desktop_launcher._compose_serve_banner(3001, [])
    assert "3001" in fallback


def test_data_dir_flag_redirects_everything(tmp_path):
    import shutil
    import subprocess
    import sys as _sys
    from pathlib import Path

    # Run a copy: from a checkout the launcher keeps its .env beside itself,
    # so running the checkout's own copy rewrote the developer's .env (its
    # APP_HOST, and a SETTINGS_ENCRYPTION_KEY that then outranks their
    # .slowbooks-master.key) — or left a new one in the tree (2.18.0 gate,
    # macbase1).
    checkout = Path(desktop_launcher.__file__).resolve().parent
    launcher = tmp_path / "desktop_launcher.py"
    shutil.copyfile(checkout / "desktop_launcher.py", launcher)
    their_env = checkout / ".env"
    before = their_env.read_bytes() if their_env.exists() else None

    target = tmp_path / "server-data"
    r = subprocess.run(
        [
            _sys.executable,
            str(launcher),
            "--setup-only",
            "--data-dir",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env={**__import__("os").environ, "SLOWBOOKS_DATA_DIR": ""},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert (target / "companies").is_dir()
    assert (tmp_path / ".env").is_file()
    assert (their_env.read_bytes() if their_env.exists() else None) == before


# ---------------------------------------------------------------------------
# Issue #52: the server child must die with its launcher parent
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="parent watcher is POSIX-only; os.kill(pid, 0) terminates on Windows",
)
def test_parent_watcher_exits_when_parent_dies(tmp_path):
    """Real process pair: a fake 'launcher' spawns a watcher child; killing
    the launcher must take the child down within the poll interval."""
    import subprocess
    import sys as _sys
    import time

    child_script = tmp_path / "child.py"
    child_script.write_text(
        "import os, sys, time\n"
        "sys.path.insert(0, %r)\n"
        "import desktop_launcher\n"
        "desktop_launcher._watch_parent(os.getppid(), poll_seconds=0.2)\n"
        "time.sleep(30)\n"
        % str(
            tmp_path.parent
            and __import__("pathlib").Path(__file__).resolve().parents[1].as_posix()
        )
    )
    parent_script = tmp_path / "parent.py"
    parent_script.write_text(
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, {str(child_script)!r}])\n"
        "print(p.pid, flush=True)\n"
        "time.sleep(30)\n"
    )
    parent = subprocess.Popen(
        [_sys.executable, str(parent_script)], stdout=subprocess.PIPE, text=True
    )
    child_pid = int(parent.stdout.readline().strip())

    # While the parent lives, the child survives several poll cycles
    time.sleep(1.0)
    import os as _os

    _os.kill(child_pid, 0)  # raises if dead — it must be alive

    # Kill the launcher; the watcher must take the child down
    parent.kill()
    parent.wait()

    def _exited(pid):
        try:
            _os.kill(pid, 0)
        except OSError:
            return True
        # The orphaned child is re-parented to PID 1. In a container whose
        # PID 1 is not an init (act, `docker run` without --init) nothing
        # reaps it, so it stays a zombie that still answers kill(pid, 0).
        # A zombie has exited — the watcher did its job.
        try:
            with open(f"/proc/{pid}/stat") as f:
                return f.read().rsplit(")", 1)[1].split()[0] == "Z"
        except OSError:
            return False

    deadline = time.time() + 5
    alive = True
    while time.time() < deadline:
        if _exited(child_pid):
            alive = False
            break
        time.sleep(0.2)
    assert not alive, "server child outlived its launcher parent"
