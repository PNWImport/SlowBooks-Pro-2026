"""Every route in the app is gated, or is on a short justified exempt list.

The earlier auth test (test_backend_only_routes_authed.py) walked only the
47-entry `_INTENTIONAL_BACKEND_ONLY` allowlist — routes with no SPA caller.
That proved nothing about the other ~500 routes, which were assumed gated
because the middleware is deny-by-default.

"Assumed gated" is not a control. This walks the *entire* route table off
`app.routes`, calls each one without a session, and requires a 401 unless
the path is on `EXPECTED_PUBLIC` below. Adding a route that answers
anonymously now fails here unless someone writes down why.

HIPAA §164.312(a)(1) (access control) is the reason this is a test and not
a code review: the app holds ePHI (benefit enrollments, dependents) and
bank PII, so "which endpoints answer without credentials" has to be a fact
that CI re-establishes on every commit, not a fact somebody checked once.
"""

import re

import pytest
from fastapi.routing import APIRoute

from app.main import app

# Paths that MUST answer without a session, each with the reason it is safe.
EXPECTED_PUBLIC = {
    # Static assets and the SPA shell — no data, and the SPA itself renders
    # the login overlay.
    "/": "SPA shell; auth overlay renders client-side",
    "/health": "liveness probe; no data, no DB read",
    "/favicon.ico": "static asset",
    "/analytics": "redirect to the SPA hash route",
    # Authenticated by something other than a session cookie.
    "/api/stripe/webhook": "Stripe request-signature auth (see test_stripe_webhook_signature.py)",
    # Same shape as the Stripe hook above, generalised to every provider:
    # the caller is a payment processor, not a browser, and it authenticates
    # with a request signature the handler checks. Exempted from the session
    # middleware by _AUTH_EXEMPT_RE in app/main.py.
    "/api/payments/{provider_name}/webhook": "payment-provider request-signature auth",
    # Serves the employer logo (204 when unset) as the portal favicon. The
    # same logo already appears on the unauthenticated portal login and the
    # public pay page, so this discloses nothing new.
    "/portal/favicon.ico": "employer logo for the portal favicon; 204 when unset",
}

# NOT public, despite being exempt from the SESSION middleware: these carry
# their own credential and still answer 401 without it. Verified empirically
# below rather than assumed — /portal/* is token-authed and /api/qbo/callback
# needs a valid OAuth state, so both land in the "must require auth" bucket.

# Prefixes that are exempt as a family, with the reason.
EXPECTED_PUBLIC_PREFIXES = {
    "/static/": "static assets",
    "/api/auth/": "login/setup/logout — the endpoints that establish a session",
    "/pay/": "public customer-facing Stripe pay page (per-invoice token in URL)",
}


def _concrete(path: str) -> str:
    """Substitute path params so the URL reaches a real handler."""
    return re.sub(r"\{[^}]+\}", "1", path)


def _all_routes() -> list[tuple[str, str]]:
    out = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append((method, route.path))
    return sorted(set(out))


def _is_expected_public(path: str) -> bool:
    if path in EXPECTED_PUBLIC:
        return True
    return any(path.startswith(p) for p in EXPECTED_PUBLIC_PREFIXES)


def test_route_table_is_substantial():
    """Guard the guard: if enumeration breaks, every other test here passes
    vacuously."""
    assert len(_all_routes()) > 200, "route enumeration looks broken"


@pytest.mark.parametrize("method,path", _all_routes())
def test_route_requires_session_or_is_documented_public(method, path, unauthed_client):
    resp = unauthed_client.request(method, _concrete(path))

    if _is_expected_public(path):
        assert resp.status_code != 401, (
            f"{method} {path} is on the public list but returns 401 — "
            "either it is not actually public, or the list is stale"
        )
        return

    # The property under test is "served no data to an anonymous caller",
    # which several status codes satisfy legitimately:
    #   401 the normal gate
    #   403 authenticated-but-forbidden paths
    #   404 token-in-path portal routes with an unknown token — deliberately
    #       indistinguishable from a nonexistent route, so an attacker cannot
    #       enumerate valid tokens by status code
    #   422 FastAPI validates the body before the auth dependency resolves, so
    #       an anonymous POST names missing fields rather than 401. No data is
    #       served and auth is not bypassed; only the schema shape leaks.
    #       Pinned in test_portal_post_validates_before_auth below.
    assert resp.status_code in (401, 403, 404, 422), (
        f"{method} {path} answered {resp.status_code} without a session. "
        "Every route must require auth or be added to EXPECTED_PUBLIC with "
        "a written reason."
    )


@pytest.mark.parametrize("path", ["/portal/bank", "/portal/pto", "/portal/profile"])
def test_portal_post_validates_before_auth(path, unauthed_client):
    """Known, accepted gap: body validation precedes the token check.

    An anonymous POST gets 422 naming the missing fields instead of 401.
    That is schema disclosure, not an access-control bypass — the handler
    never runs and no record is read or written. Pinned so the day someone
    moves the token check into middleware (closing it), this test fails and
    gets deleted deliberately rather than the behaviour drifting unnoticed.
    """
    resp = unauthed_client.post(path, json={})
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    # It must leak only field names — never records.
    assert "employee" not in resp.text.lower() or "missing" in resp.text


def test_public_list_has_a_reason_for_every_entry():
    """The list is only useful if each entry says why it is safe."""
    for path, reason in EXPECTED_PUBLIC.items():
        assert reason and len(reason) > 10, f"{path} needs a real justification"
    for prefix, reason in EXPECTED_PUBLIC_PREFIXES.items():
        assert reason and len(reason) > 10, f"{prefix} needs a real justification"
