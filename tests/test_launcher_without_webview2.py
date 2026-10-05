import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

import desktop_launcher as dl

GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


class FakeWinreg:
    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, values):
        self.values = values

    def OpenKey(self, root, path):
        if (root, path) not in self.values:
            raise OSError(2, "not found")
        key = (root, path)

        class Key:
            def __enter__(self):
                return key

            def __exit__(self, *args):
                return False

        return Key()

    def QueryValueEx(self, key, name):
        assert name == "pv"
        return self.values[key], 1


def with_registry(monkeypatch, values):
    monkeypatch.setattr(dl.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg(values))


def test_webview2_registry_detection(monkeypatch):
    keys = [
        ("HKLM", rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{GUID}"),
        ("HKLM", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{GUID}"),
        ("HKCU", rf"Software\Microsoft\EdgeUpdate\Clients\{GUID}"),
    ]
    for key in keys:
        with_registry(monkeypatch, {key: "120.0.2210.91"})
        assert dl._webview2_installed() is True
    with_registry(monkeypatch, {})
    assert dl._webview2_installed() is False
    with_registry(monkeypatch, {keys[1]: "0.0.0.0"})
    assert dl._webview2_installed() is False
    monkeypatch.setattr(dl.sys, "platform", "darwin")
    assert dl._webview2_installed() is True


def test_messages_only_offer_executable_remedies(monkeypatch):
    monkeypatch.setattr(dl, "FROZEN", True)
    frozen = dl._no_webview2_message()
    assert "python" not in frozen.lower()
    assert dl.WEBVIEW2_URL in frozen and dl.WINDOWS_INSTALLER in frozen
    iss = (Path(dl.ROOT) / "packaging/windows/SlowBooksPro.iss").read_text(
        encoding="utf-8"
    )
    match = re.search(r"^OutputBaseFilename=(\S+)", iss, re.M)
    assert match and dl.WINDOWS_INSTALLER == match.group(1) + ".exe"

    monkeypatch.setattr(dl, "FROZEN", False)
    checkout = dl._no_webview2_message()
    flag = re.search(r"python desktop_launcher\.py (--\S+)", checkout)
    assert flag
    result = subprocess.run(
        [sys.executable, str(Path(dl.ROOT) / "desktop_launcher.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert flag.group(1) in result.stdout


class Proc:
    def poll(self):
        return None


@pytest.fixture
def browser_run(monkeypatch):
    calls = {"launch": [], "opened": [], "held": [], "stopped": []}
    proc = Proc()
    from app.services import company_service

    monkeypatch.setattr(company_service, "get_last_opened", lambda: "books.db")
    monkeypatch.setattr(
        dl,
        "launch_company",
        lambda filename, port, output=None, bind_host="127.0.0.1", persist=True: (
            calls["launch"].append((filename, port, bind_host, persist)),
            proc,
        )[1],
    )
    monkeypatch.setattr(dl, "stop_server", lambda value: calls["stopped"].append(value))
    monkeypatch.setattr(
        dl,
        "_hold_until_dismissed",
        lambda message, title="": calls["held"].append(message),
    )
    monkeypatch.setitem(
        sys.modules,
        "webbrowser",
        types.SimpleNamespace(open=lambda url: calls["opened"].append(url)),
    )
    return calls, proc


def test_browser_fallback_serves_loopback_and_stops(monkeypatch, browser_run):
    calls, proc = browser_run
    with_registry(monkeypatch, {})
    monkeypatch.setattr(dl, "_ask_yes_no", lambda message, title="": True)
    monkeypatch.setattr(dl, "_show_error_box", lambda message: pytest.fail(message))
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace())
    assert dl.run_window(3001) == 0
    assert calls["launch"] == [("books.db", 3001, "127.0.0.1", False)]
    assert calls["opened"] == ["http://127.0.0.1:3001"]
    assert calls["held"] and calls["stopped"] == [proc]


def test_declined_fallback_starts_nothing(monkeypatch, browser_run):
    calls, _ = browser_run
    with_registry(monkeypatch, {})
    monkeypatch.setattr(dl, "_ask_yes_no", lambda message, title="": False)
    shown = []
    monkeypatch.setattr(dl, "_show_error_box", shown.append)
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace())
    assert dl.run_window(3001) == 1
    assert calls["launch"] == [] and calls["opened"] == []
    assert shown and dl.WEBVIEW2_URL in shown[0]


def test_question_is_windows_only(monkeypatch):
    monkeypatch.setattr(dl.sys, "platform", "linux")
    assert dl._ask_yes_no("anything") is False
