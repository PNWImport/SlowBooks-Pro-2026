import ctypes
import sys
import types

import pytest

import desktop_launcher as dl


class Calls:
    def __init__(self):
        self.log = []


class FakeWinmm:
    def __init__(self, calls, refuse=False):
        self.calls = calls
        self.refuse = refuse

    def timeBeginPeriod(self, ms):
        self.calls.log.append(("timeBeginPeriod", ms))
        return 97 if self.refuse else 0

    def timeEndPeriod(self, ms):
        self.calls.log.append(("timeEndPeriod", ms))
        return 0


class FakeKernel32:
    def __init__(self, calls):
        self.calls = calls

    def GetCurrentProcess(self):
        return -1

    def SetProcessInformation(self, handle, klass, ptr, size):
        state = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 3)).contents
        self.calls.log.append(
            ("SetProcessInformation", handle, klass, tuple(state), size)
        )
        return 1


class FakeNtdll:
    def __init__(self, calls):
        self.calls = calls

    def NtQueryTimerResolution(self, lo, hi, current):
        raised = any(call[0] == "timeBeginPeriod" for call in self.calls.log)
        current._obj.value = 10_000 if raised else 156_250
        return 0


def fake_windows(monkeypatch, *, refuse=False, env="1"):
    calls = Calls()
    monkeypatch.setattr(dl.sys, "platform", "win32")
    if env is None:
        monkeypatch.delenv("SLOWBOOKS_TIMER_RESOLUTION_MS", raising=False)
    else:
        monkeypatch.setenv("SLOWBOOKS_TIMER_RESOLUTION_MS", env)
    monkeypatch.setattr(
        dl,
        "_win32_dlls",
        lambda: (FakeWinmm(calls, refuse), FakeKernel32(calls), FakeNtdll(calls)),
    )
    return calls


def test_requests_timer_and_matches_end(monkeypatch, capsys):
    calls = fake_windows(monkeypatch)
    undo = dl.raise_timer_resolution()
    assert [call[0] for call in calls.log] == [
        "SetProcessInformation",
        "timeBeginPeriod",
    ]
    _, handle, klass, state, size = calls.log[0]
    assert (handle, klass, state, size) == (-1, 4, (1, 0x4, 0), 12)
    assert "was 15.625 ms, now 1.000 ms" in capsys.readouterr().out
    undo()
    assert calls.log[-1] == ("timeEndPeriod", 1)


def test_refused_request_is_not_ended(monkeypatch, capsys):
    calls = fake_windows(monkeypatch, refuse=True)
    dl.raise_timer_resolution()()
    assert "refused" in capsys.readouterr().out
    assert ("timeEndPeriod", 1) not in calls.log


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_non_windows_is_noop(monkeypatch, platform):
    monkeypatch.setattr(dl.sys, "platform", platform)
    called = []
    monkeypatch.setattr(dl, "_win32_dlls", lambda: called.append(True))
    dl.raise_timer_resolution()()
    assert called == []


def test_off_by_default_and_invalid_setting(monkeypatch, capsys):
    calls = fake_windows(monkeypatch, env=None)
    dl.raise_timer_resolution()()
    assert calls.log == []
    assert "SLOWBOOKS_TIMER_RESOLUTION_MS=1" in capsys.readouterr().out

    calls = fake_windows(monkeypatch, env="fast")
    dl.raise_timer_resolution()()
    assert calls.log == []
    assert "'fast' is not a number" in capsys.readouterr().out


def test_serve_always_restores_timer(monkeypatch):
    order = []
    monkeypatch.setattr(
        dl,
        "raise_timer_resolution",
        lambda: order.append("raise") or (lambda: order.append("undo")),
    )
    monkeypatch.setattr(dl, "_watch_parent", lambda pid: None)
    monkeypatch.setattr(dl.sys, "platform", "linux")
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        types.SimpleNamespace(
            run=lambda *args, **kwargs: order.append("run")
            or (_ for _ in ()).throw(RuntimeError("boom"))
        ),
    )
    with pytest.raises(RuntimeError, match="boom"):
        dl._serve()
    assert order == ["raise", "run", "undo"]
