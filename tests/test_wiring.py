"""
Wiring audit as a unit test.

Greps every JS file for `API.get/post/put/del('/path')` calls, normalizes
the path templates (template-literal interpolation becomes `{x}` path
params), and asserts every one resolves to a registered FastAPI route
with a matching method.

The same audit was historically done by hand (see docs/wiring-audit.md).
This test catches regressions automatically: rename a route, forget to
update the SPA, and CI fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parents[1] / "app" / "static" / "js"

# API.get('/foo') | API.post(`/foo/${id}`, ...) | API.put('/foo', data) | API.del(`/foo/${id}`)
# Captures the method and the FIRST argument string (single, double, or backtick quoted).
_API_CALL = re.compile(
    r"""API\.(get|post|put|del)\(\s*['"`]([^'"`,]+)['"`]""",
    re.MULTILINE,
)


def _normalize_js_path(raw: str) -> str:
    """JS path string -> /api-prefixed, query-stripped path with `${x}` -> `*`.

    `*` marks "an interpolation went here" — distinct from literal segments
    so we know which positions were dynamic on the call side.
    """
    path = raw.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]+\}", "*", path)
    if not path.startswith("/api"):
        path = "/api" + (path if path.startswith("/") else "/" + path)
    return path


@pytest.fixture(scope="module")
def app_routes():
    """List of (METHOD, [path_segments]) for every registered FastAPI route."""
    from app.main import app

    out = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        segs = route.path.split("/")
        for m in methods:
            out.append((m.upper(), segs))
    return out


def _route_matches(call_segs: list[str], route_segs: list[str]) -> bool:
    """A JS call matches a FastAPI route iff segment counts are equal AND
    each segment either matches literally or the route side is a `{...}`
    path param (which absorbs any literal or `*` on the call side)."""
    if len(call_segs) != len(route_segs):
        return False
    for call, route in zip(call_segs, route_segs):
        if route.startswith("{") and route.endswith("}"):
            continue  # param slot matches anything
        if call == route:
            continue
        return False
    return True


def _collect_api_calls():
    """Walk app/static/js/*.js, yield (file, line, method, normalized_path)."""
    for js in sorted(JS_DIR.glob("*.js")):
        text = js.read_text(encoding="utf-8")
        if js.name == "api.js":
            continue
        for match in _API_CALL.finditer(text):
            method, raw = match.group(1), match.group(2)
            method = "DELETE" if method == "del" else method.upper()
            line = text.count("\n", 0, match.start()) + 1
            yield js.name, line, method, _normalize_js_path(raw)


def test_every_js_api_call_resolves_to_a_route(app_routes):
    """Every API.get/post/put/del in the SPA must hit a real handler."""
    orphans = []
    for file, line, method, path in _collect_api_calls():
        call_segs = path.split("/")
        matched = any(
            rm == method and _route_matches(call_segs, rsegs)
            for rm, rsegs in app_routes
        )
        if not matched:
            orphans.append(f"  {file}:{line}  {method} {path}")
    assert not orphans, "JS API calls without matching FastAPI handlers:\n" + "\n".join(
        orphans
    )


def test_collector_finds_something():
    """Smoke test for the collector itself — if this asserts 0 calls,
    the regex broke."""
    calls = list(_collect_api_calls())
    assert len(calls) > 20, (
        f"_collect_api_calls() only found {len(calls)} entries — the regex "
        "is probably broken. Spot-check app/static/js/payroll.js."
    )
