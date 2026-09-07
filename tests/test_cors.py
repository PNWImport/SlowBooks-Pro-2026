"""
CORS must NOT return allow_origin=* plus allow_credentials=true.
Must respond with a locked-down origin allow-list.
"""


def test_cors_does_not_return_wildcard(client):
    r = client.options(
        "/api/auth/status",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Starlette returns 200 on OPTIONS with matching headers or 400 on reject.
    # Either way, the allow-origin header MUST NOT be "*".
    allow_origin = r.headers.get("access-control-allow-origin", "")
    assert allow_origin != "*"


def test_cors_allows_configured_origin(client):
    """Whitelisted origin (set in conftest.py ALLOWED_ORIGINS) should echo."""
    r = client.options(
        "/api/auth/status",
        headers={
            "Origin": "http://localhost:3001",
            "Access-Control-Request-Method": "GET",
        },
    )
    allow_origin = r.headers.get("access-control-allow-origin", "")
    # Either the exact origin echoed back, or not present (denied) — but
    # never "*" combined with credentials.
    if allow_origin:
        assert allow_origin == "http://localhost:3001"


# ---------------------------------------------------------------------------
# Regression: CORS and the security headers must sit OUTSIDE the session gate.
#
# Both were registered before require_session, which made them the INNER
# layers (Starlette: last added = outermost). The gate then answered every
# preflight 401 with no Access-Control-Allow-Origin — browsers send
# preflights without credentials, so a correct CORS_ALLOW_ORIGINS still
# failed every cross-origin call — and every 401 shipped with no CSP at
# all, which is the pre-login state of a browser.
#
# These probe a GATED route on purpose. The pre-existing tests above only
# hit /api/auth/status, which is auth-exempt, so the stack could be
# inverted and they would still pass.
# ---------------------------------------------------------------------------


def test_preflight_on_a_gated_route_is_answered_not_401(unauthed_client):
    """A preflight carries no cookie by design; the gate must not eat it."""
    r = unauthed_client.options(
        "/api/customers",
        headers={
            "Origin": "http://localhost:3001",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code != 401, (
        "preflight hit the session gate — CORSMiddleware is registered "
        "inside require_session instead of outside it"
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3001"


def test_unlisted_origin_is_still_refused_on_a_gated_route(unauthed_client):
    r = unauthed_client.options(
        "/api/customers",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") in (None, "")


def test_security_headers_are_present_on_a_401(unauthed_client):
    """The unauthenticated 401 is what an unlogged-in browser actually gets."""
    r = unauthed_client.get("/api/customers")
    assert r.status_code == 401
    for header in (
        "content-security-policy",
        "x-frame-options",
        "x-content-type-options",
        "referrer-policy",
    ):
        assert r.headers.get(header), f"{header} missing from a 401 response"
