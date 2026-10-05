"""Issue #107: on Windows about half of all requests waited one 15.625 ms
scheduler tick. The server child asks for a 1 ms timer while it serves, and
tells Windows 11 not to ignore that request from a windowless process.

There is no Windows here, so the calls are pinned against fakes: which DLL
entry points, with which arguments, in which order, and that the request is
matched by timeEndPeriod when the server stops. Whether the median actually
moves is measured on the gate, on real hardware, from the log line this
prints — not asserted here.
"""

import ctypes

import desktop_launcher as dl


class _Calls:
    def __init__(self):
        self.log = []


class _FakeWinmm:
    def __init__(self, calls, refuse=False):
        self.calls, self.refuse = calls, refuse

    def timeBeginPeriod(self, ms):
        self.calls.log.append(("timeBeginPeriod", ms))
        return 97 if self.refuse else 0  # TIMERR_NOCANDO / TIMERR_NOERROR

    def timeEndPeriod(self, ms):
        self.calls.log.append(("timeEndPeriod", ms))
        return 0


class _FakeKernel32:
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


class _FakeNtdll:
    """Resolution reads 15.625 ms until timeBeginPeriod ran, then 1 ms."""

    def __init__(self, calls):
        self.calls = calls

    def NtQueryTimerResolution(self, lo, hi, cur):
        raised = any(c[0] == "timeBeginPeriod" for c in self.calls.log)
        cur._obj.value = 10_000 if raised else 156_250
        return 0


def _fake_windows(monkeypatch, refuse=False, env="1"):
    calls = _Calls()
    monkeypatch.setattr(dl.sys, "platform", "win32")
    if env is None:
        monkeypatch.delenv("SLOWBOOKS_TIMER_RESOLUTION_MS", raising=False)
    else:
        monkeypatch.setenv("SLOWBOOKS_TIMER_RESOLUTION_MS", env)
    monkeypatch.setattr(
        dl,
        "_win32_dlls",
        lambda: (_FakeWinmm(calls, refuse), _FakeKernel32(calls), _FakeNtdll(calls)),
    )
    return calls


def test_requests_one_ms_and_opts_out_of_windows_11_throttling(monkeypatch, capsys):
    calls = _fake_windows(monkeypatch)
    undo = dl.raise_timer_resolution()
    names = [c[0] for c in calls.log]
    # the opt-out comes first, so the request that follows is honoured
    assert names == ["SetProcessInformation", "timeBeginPeriod"]
    _, handle, klass, state, size = calls.log[0]
    assert handle == -1 and klass == 4  # ProcessPowerThrottling
    # Version 1; ControlMask selects IGNORE_TIMER_RESOLUTION (0x4);
    # StateMask 0 turns that throttle OFF = "always honor timer requests"
    assert state == (1, 0x4, 0) and size == 12
    assert calls.log[1] == ("timeBeginPeriod", 1)
    out = capsys.readouterr().out
    assert "timer resolution: was 15.625 ms, now 1.000 ms" in out
    undo()
    assert calls.log[-1] == ("timeEndPeriod", 1)  # matched, as the docs require


def test_a_refused_request_is_reported_and_never_ended(monkeypatch, capsys):
    calls = _fake_windows(monkeypatch, refuse=True)
    undo = dl.raise_timer_resolution()
    assert "refused" in capsys.readouterr().out
    undo()
    assert ("timeEndPeriod", 1) not in calls.log


def test_nothing_happens_off_windows(monkeypatch):
    monkeypatch.setattr(dl.sys, "platform", "linux")
    called = []
    monkeypatch.setattr(dl, "_win32_dlls", lambda: called.append(1))
    dl.raise_timer_resolution()()
    assert called == []


def test_serve_restores_the_timer_when_uvicorn_returns(monkeypatch):
    """The undo runs in a finally — a crash out of uvicorn.run still ends
    the period, which is what "matched call" means in practice."""
    import types

    order = []
    monkeypatch.setattr(
        dl,
        "raise_timer_resolution",
        lambda: order.append("raise") or (lambda: order.append("undo")),
    )
    monkeypatch.setattr(dl, "_watch_parent", lambda pid: None)
    fake_uvicorn = types.SimpleNamespace(
        run=lambda *a, **kw: order.append("run")
        or (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", fake_uvicorn)
    try:
        dl._serve()
    except RuntimeError:
        pass
    assert order == ["raise", "run", "undo"]


def test_off_by_default_and_the_log_says_how_to_turn_it_on(monkeypatch, capsys):
    """2.13.0 gate: the 15.625 ms symptom did not reproduce on a box put
    back at the default, so the 1 ms timer is not imposed on every install.
    The log line still names the switch, so the instrument is findable."""
    calls = _fake_windows(monkeypatch, env=None)
    dl.raise_timer_resolution()()
    assert calls.log == []
    out = capsys.readouterr().out
    assert (
        "left at the system default" in out and "SLOWBOOKS_TIMER_RESOLUTION_MS=1" in out
    )


def test_a_non_number_is_named_not_swallowed(monkeypatch, capsys):
    calls = _fake_windows(monkeypatch, env="fast")
    dl.raise_timer_resolution()()
    assert calls.log == [] and "'fast' is not a number" in capsys.readouterr().out
