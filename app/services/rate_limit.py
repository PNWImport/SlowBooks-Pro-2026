# ============================================================================
# Slowbooks Pro 2026 — Rate limiter (Phase 9.7)
#
# Shared slowapi Limiter instance. Lives in its own module so
# app.routes.analytics and app.main can both import it without creating
# a circular dependency.
#
# Toggle with RATE_LIMIT_ENABLED env var (default on). Tests set this to
# "0" in conftest.py so decorator calls don't bleed per-test counters.
# ============================================================================

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

_enabled = os.environ.get("RATE_LIMIT_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

# Where the counters live. Unset = slowapi's in-process MemoryStorage, which
# is correct for a single-worker container and WRONG the moment there is
# more than one: every uvicorn worker and every replica keeps its own tally,
# so a "5 per minute" login limit becomes 5 x workers x replicas. Compose
# defaults to one worker. Point this at shared storage (for example,
# redis://redis:6379/0) before increasing workers or adding replicas;
# app.main warns loudly when it is unset in a configuration where it matters.
RATE_LIMIT_STORAGE_URI = os.environ.get("RATE_LIMIT_STORAGE_URI", "").strip()

limiter = Limiter(
    key_func=get_remote_address,
    enabled=_enabled,
    **({"storage_uri": RATE_LIMIT_STORAGE_URI} if RATE_LIMIT_STORAGE_URI else {}),
)
