"""A headless launch (--serve-lan / --no-window) must not rewrite the desktop
app's .env DATABASE_URL or last-opened company (issue #110): the server takes
its DATABASE_URL from the environment start_server() builds."""

import desktop_launcher as dl
import pytest


class _Proc:
    pid = 1

    def poll(self):
        return None


def _stub_launch(monkeypatch, tmp_path):
    calls = {"env": [], "last": [], "migrate": 0, "start": [], "health": []}
    from app.services import company_service

    monkeypatch.setattr(dl, "_server_already_running", lambda port: False)
    monkeypatch.setattr(company_service, "company_db_path", lambda f: tmp_path / f)
    monkeypatch.setattr(dl, "set_env_value", lambda k, v: calls["env"].append((k, v)))
    monkeypatch.setattr(
        company_service, "set_last_opened", lambda f: calls["last"].append(f)
    )
    monkeypatch.setattr(
        dl,
        "migrate",
        lambda url, output=None: calls.__setitem__("migrate", calls["migrate"] + 1),
    )
    monkeypatch.setattr(
        dl,
        "start_server",
        lambda url, port, output=None, bind_host="127.0.0.1": (
            calls["start"].append((url, bind_host)),
            _Proc(),
        )[1],
    )
    monkeypatch.setattr(
        dl,
        "wait_for_health",
        lambda proc, port, host="127.0.0.1", tls=False: (
            calls["health"].append((host, tls)),
            True,
        )[1],
    )
    return calls


def test_headless_launch_leaves_desktop_state_alone(monkeypatch, tmp_path):
    calls = _stub_launch(monkeypatch, tmp_path)
    dl.launch_company("books.db", 3999, bind_host="0.0.0.0", persist=False)
    assert calls["env"] == [] and calls["last"] == []
    assert calls["migrate"] == 1  # it still migrates the file it serves
    ((url, host),) = calls["start"]
    assert url.endswith("books.db") and host == "0.0.0.0"
    assert calls["health"] == [("127.0.0.1", True)]


def test_windowed_launch_still_records_the_choice(monkeypatch, tmp_path):
    calls = _stub_launch(monkeypatch, tmp_path)
    dl.launch_company("books.db", 3999)
    assert [k for k, _ in calls["env"]] == ["DATABASE_URL"]
    assert calls["last"] == ["books.db"]
    assert calls["health"] == [("127.0.0.1", False)]


def test_failed_headless_launch_cleans_child_without_persisting(monkeypatch, tmp_path):
    calls = _stub_launch(monkeypatch, tmp_path)
    stopped = []
    monkeypatch.setattr(dl, "wait_for_health", lambda *a, **k: False)
    monkeypatch.setattr(dl, "stop_server", stopped.append)
    with pytest.raises(RuntimeError, match="healthy"):
        dl.launch_company("books.db", 3999, bind_host="0.0.0.0", persist=False)
    assert len(stopped) == 1
    assert calls["env"] == [] and calls["last"] == []


def test_run_headless_passes_persist_false(monkeypatch, tmp_path):
    """The --serve-lan / --no-window entry point is the one that must not persist."""
    seen = {}

    def fake_launch(filename, port, output=None, bind_host="127.0.0.1", persist=True):
        seen["persist"] = persist
        raise RuntimeError("stop here")

    from app.services import company_service

    monkeypatch.setattr(company_service, "get_last_opened", lambda: "books.db")
    monkeypatch.setattr(dl, "launch_company", fake_launch)
    assert dl.run_headless(3999, bind_host="127.0.0.1") == 1
    assert seen["persist"] is False


def test_lan_headless_still_requires_tls_before_launch(monkeypatch):
    def missing_tls():
        raise ValueError("TLS configuration required")

    def forbidden(*args, **kwargs):
        pytest.fail("Must not launch without LAN TLS")

    monkeypatch.setattr(dl, "_lan_tls", missing_tls)
    monkeypatch.setattr(dl, "launch_company", forbidden)
    assert dl.run_headless(3999, bind_host="0.0.0.0") == 1
