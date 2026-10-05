"""FX conversion must fail safely on unavailable or malformed rate responses."""

import io
import json
from decimal import Decimal
from urllib.error import URLError

import pytest

from app.services import fx_service as fx


@pytest.fixture
def remote_fx(monkeypatch):
    responses = {}
    calls = []

    def open_response(request, timeout):
        assert timeout == fx.TIMEOUT_SECONDS
        assert request.full_url.startswith(fx.VALET_BASE + "/")
        calls.append(request.full_url)
        series = request.full_url.split("/")[-2]
        payload = responses.get(series, URLError("synthetic unavailable"))
        if isinstance(payload, Exception):
            raise payload
        response = io.BytesIO(
            payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        )
        response.status = 200
        return response

    monkeypatch.setattr(fx.urllib.request, "urlopen", open_response)
    return responses, calls


def observation(series, value, day="2026-01-02"):
    return {"observations": [{"d": day, series: {"v": value}}]}


def test_identity_and_missing_currency_do_not_fetch(remote_fx):
    assert fx.get_rate("usd", "USD")["rate"] == Decimal("1")
    assert fx.get_rate(None, "USD")["error"] == "missing currency code"
    assert remote_fx[1] == []


def test_direct_rate_preserves_precision(remote_fx):
    remote_fx[0]["FXUSDCAD"] = observation("FXUSDCAD", "1.23456789")
    assert fx.get_rate("usd", "cad") == {
        "rate": Decimal("1.23456789"),
        "observation_date": "2026-01-02",
        "source": "bankofcanada-direct",
        "error": None,
    }


def test_cross_rate_uses_older_leg_date(remote_fx):
    remote_fx[0]["FXEURCAD"] = observation("FXEURCAD", "1.5", "2026-01-03")
    remote_fx[0]["FXUSDCAD"] = observation("FXUSDCAD", "1.25", "2026-01-02")
    assert fx.get_rate("EUR", "USD") == {
        "rate": Decimal("1.20000000"),
        "observation_date": "2026-01-02",
        "source": "bankofcanada-cross",
        "error": None,
    }
    assert len(remote_fx[1]) == 3


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"observations": []},
        {"observations": [{}]},
        observation("FXUSDCAD", None),
        observation("FXUSDCAD", ""),
        observation("FXUSDCAD", "invalid"),
        b"not-json",
        b"\xff",
        [],
        {"observations": "bad"},
        {"observations": [None]},
        {"observations": [{"FXUSDCAD": "bad"}]},
        observation("FXUSDCAD", "NaN"),
        observation("FXUSDCAD", "Infinity"),
        observation("FXUSDCAD", "-1"),
        observation("FXUSDCAD", "0"),
        URLError("synthetic network failure"),
        TimeoutError("synthetic timeout"),
    ],
)
def test_bad_response_returns_unavailable(remote_fx, payload):
    remote_fx[0]["FXUSDCAD"] = payload
    result = fx.get_rate("USD", "CAD")
    assert result == {
        "rate": None,
        "observation_date": None,
        "source": None,
        "error": "rate unavailable",
    }


def test_non_success_status_is_unavailable(monkeypatch):
    response = io.BytesIO(b"{}")
    response.status = 503
    monkeypatch.setattr(fx.urllib.request, "urlopen", lambda *args, **kwargs: response)
    assert fx.get_rate("USD", "CAD")["rate"] is None


def test_unavailable_cross_leg_returns_error(remote_fx):
    remote_fx[0]["FXEURCAD"] = observation("FXEURCAD", "1.5")
    assert fx.get_rate("EUR", "USD")["rate"] is None
