# ============================================================================
# Decompiled from qbw32.exe!CQBPreferences + CCompanyInfo
# Offset: 0x0023F000 (Prefs) / 0x00241200 (CompanyInfo)
# Original stored in Windows Registry: HKCU\Software\Intuit\QuickBooks\12.0
# and in the .QBW file header (first 512 bytes, encrypted with XOR 0x1F).
# We moved everything to .env because it's 2026 and registry is not a config.
# ============================================================================

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://bookkeeper:bookkeeper@localhost:5432/bookkeeper"
)
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "3001"))
APP_DEBUG = os.getenv("APP_DEBUG", "false").lower() == "true"

# ---- HTTPS / Transport Security ----
# FORCE_HTTPS=true enables app-level HTTPS redirect + Strict-Transport-Security.
# Defaults to True in production (APP_DEBUG=false). Set to False only when you
# know a proxy in front already terminates TLS and you do NOT want the app to
# 308-redirect plain HTTP (e.g. health-check probes from inside a VPC).
FORCE_HTTPS = (
    os.getenv("FORCE_HTTPS", "false" if APP_DEBUG else "true").lower() == "true"
)
# Two years is the HSTS preload-list minimum (and the value most browsers cache).
HSTS_MAX_AGE = int(os.getenv("HSTS_MAX_AGE", "63072000"))

# ---- Proxy trust ----
# X-Forwarded-For is client-controllable on a direct (non-proxied) deploy, so
# trusting it blindly lets an attacker forge the IP in the login/portal audit
# trail (and, if a proxy is later added that the limiter trusts, evade rate
# limits). Only honor XFF when you actually run behind a trusted reverse proxy
# that sets it. Default off → use the socket peer.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"

# ---- Session idle timeout ----
# Sliding-window inactivity cap on the session cookie. The cookie itself has
# a 30-day hard expiry; this trims long-lived idle sessions on top of that.
# Set to 0 to disable (useful for local dev and the test harness).
SESSION_IDLE_TIMEOUT_SECONDS = int(
    os.getenv("SESSION_IDLE_TIMEOUT_SECONDS", "14400")  # 4 hours
)


def resolve_cors_origins(env: dict | None = None) -> list[str]:
    """Return the explicit CORS origin allowlist for the FastAPI app.

    Defaults to loopback-only so a fresh install cannot be hit cross-origin
    from arbitrary websites. Override with the CORS_ALLOW_ORIGINS env var
    (comma-separated) when the UI is served from a different trusted origin.
    """
    env = env if env is not None else os.environ
    explicit = (env.get("CORS_ALLOW_ORIGINS") or "").strip()
    if explicit:
        return [o.strip() for o in explicit.split(",") if o.strip()]
    port = str(env.get("APP_PORT", "3001")).strip() or "3001"
    return [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]


CORS_ALLOW_ORIGINS = resolve_cors_origins()

# CCompanyInfo fields — originally at .QBW header offset 0x40
COMPANY_NAME = os.getenv("COMPANY_NAME", "My Company")
COMPANY_ADDRESS = os.getenv("COMPANY_ADDRESS", "")
COMPANY_PHONE = os.getenv("COMPANY_PHONE", "")
COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "")
DEFAULT_TERMS = os.getenv("DEFAULT_TERMS", "Net 30")
DEFAULT_TAX_RATE = float(os.getenv("DEFAULT_TAX_RATE", "0.0"))

# Secret used to derive the symmetric key that encrypts payroll PII at rest
# (employee bank routing/account numbers). MUST be overridden in production —
# the development default below is well-known and provides no real protection.
PAYROLL_ENCRYPTION_SECRET = os.getenv(
    "PAYROLL_ENCRYPTION_SECRET", "slowbooks-dev-payroll-key-change-me"
)

# Employer identifiers and rates used by payroll tax forms / state engines.
EMPLOYER_EIN = os.getenv("EMPLOYER_EIN", "")
EMPLOYER_STATE = os.getenv("EMPLOYER_STATE", "WA")
# State unemployment (SUTA) experience rate as a decimal, e.g. 0.012 for 1.2%.
# This is the rate for the employer's home state (EMPLOYER_STATE above).
SUTA_RATE = float(os.getenv("SUTA_RATE", "0.012"))


def _parse_state_rates(raw: str) -> dict:
    """Parse a "WA:0.012,OR:0.021" rate list into {state: rate}.

    Malformed pairs are skipped rather than raising: a typo in an environment
    variable should not stop the application from booting, and the per-state
    resolver already falls back to the state's new-employer rate.
    """
    rates: dict[str, float] = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        state, _, value = pair.partition(":")
        state = state.strip().upper()
        if len(state) != 2:
            continue
        try:
            rates[state] = float(value.strip())
        except ValueError:
            continue
    return rates


# Per-state SUTA experience rates for multi-state employers, as a
# comma-separated "ST:rate" list — e.g. SUTA_RATE_BY_STATE="WA:0.0121,OR:0.024".
# States assign each employer its own experience rate, so applying one rate
# across every state (which a single SUTA_RATE does) is wrong the moment you
# hire outside your home state. Unlisted states fall back to the state's
# new-employer rate from its tax table, then to SUTA_RATE.
SUTA_RATE_BY_STATE = _parse_state_rates(os.getenv("SUTA_RATE_BY_STATE", ""))

# Minimum-wage floors for tipped-employee top-up math. Federal defaults;
# set your state/city floor when it is higher — the top-up guarantee uses
# MINIMUM_WAGE, and the FICA tip credit (Form 8846) is statutorily pinned
# to the 2007 federal minimum of $5.15 regardless of these.
MINIMUM_WAGE = float(os.getenv("MINIMUM_WAGE", "7.25"))
TIPPED_MINIMUM_WAGE = float(os.getenv("TIPPED_MINIMUM_WAGE", "2.13"))

# When true, a state tax table whose `verified` flag is still false withholds
# NO state income tax and labels the omission on the pay stub, instead of
# withholding an amount nobody has reviewed. Off by default — an approximate
# withholding is usually closer than zero — but operators running live payroll
# may prefer to fail loud. See app/services/state_tax/table_engine.py.
PAYROLL_STRICT_TAX_TABLES = os.getenv("PAYROLL_STRICT_TAX_TABLES", "").lower() in (
    "1",
    "true",
    "yes",
)
