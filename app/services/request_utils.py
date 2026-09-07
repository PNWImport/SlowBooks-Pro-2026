# ============================================================================
# Shared request helpers used across route modules.
# ============================================================================

from fastapi import Request


def client_ip(request: Request) -> str:
    """Best-effort client IP. Honors X-Forwarded-For ONLY when the deployment
    declares it runs behind a trusted proxy (TRUST_PROXY_HEADERS) — otherwise
    XFF is client-spoofable and would let an attacker forge the audited IP.
    Direct deploys fall back to the socket peer."""
    from app.config import TRUST_PROXY_HEADERS

    fwd = request.headers.get("x-forwarded-for", "") if TRUST_PROXY_HEADERS else ""
    if fwd:
        # Take the first hop — that's the client (proxies append to the right).
        return fwd.split(",")[0].strip()[:45]
    client = request.client
    return (client.host if client else "")[:45]
