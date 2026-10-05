# ============================================================================
# Slowbooks Pro 2026 — AI Insights service (Phase 9.5)
#
# Runs the analytics dashboard through an LLM and returns a structured
# "3 observations / 3 risks / 3 recommendations" report. Eight adapters
# have curated September-2026 defaults; every model ID remains editable so
# vendor releases and account-specific snapshots do not require an app update.
#
# Providers (catalogues reviewed September 2026):
#   * grok        — xAI, OpenAI-compat,    https://api.x.ai/v1
#   * groq        — Groq LPU cloud, OpenAI-compat, https://api.groq.com/openai/v1
#   * cloudflare  — Cloudflare Workers AI, OpenAI-compat, account-scoped URL
#   * cloudflare_worker — self-hosted Workers AI gateway
#   * anthropic   — Claude native /v1/messages
#   * openai      — OpenAI /v1/chat/completions
#   * gemini      — Google generativelanguage.googleapis.com generateContent
#   * custom       — any OpenAI-compatible /v1/chat/completions endpoint
#                   (user-supplied base URL, HTTPS-only, SSRF-guarded)
#
# Every network call goes through httpx with a 60-second timeout. API keys
# are passed in from the caller — this module has no database access and
# never logs key material.
# ============================================================================

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)

# Cloudflare account IDs are exactly 32 lowercase hex chars.
# Validate before interpolating into URLs to prevent SSRF.
CLOUDFLARE_ACCOUNT_ID_RE = re.compile(r"^[a-f0-9]{32}$")

# Hosts that must never be accepted as a user-supplied Worker URL.
_BLOCKED_WORKER_HOSTS = {
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
    "broadcasthost",
    "0.0.0.0",
}

# Max length for a user-supplied URL (defense against absurd inputs).
_MAX_WORKER_URL_LEN = 2048


def validate_worker_url(url: str) -> str:
    """Validate + normalise a user-supplied Cloudflare Worker URL.

    Security guarantees enforced here (every one of these is a mitigation
    for a real attack we care about):

      * **MITM**: only `https://` accepted. Plain HTTP, `file://`,
        `javascript:`, `ftp://`, `gopher://` etc. are rejected outright,
        so a tampered network path cannot downgrade or redirect the
        request to cleartext or a non-HTTP scheme.
      * **SSRF**: hostnames that resolve to (or literally *are*) loopback,
        link-local, private, multicast, unspecified, or reserved ranges
        are rejected. So is `localhost` and friends. A compromised
        Slowbooks install can't be pointed at `http://127.0.0.1:5000/admin`
        or the AWS metadata service at `169.254.169.254`.
      * **Credential leakage**: embedded userinfo (`https://user:pw@host`)
        is rejected — we never want a password fragment flowing through
        our settings table or error messages.
      * **Injection**: control characters, whitespace inside the URL,
        and otherwise unparseable inputs are rejected before the URL is
        interpolated into anything.
      * **DoS**: max length 2048 chars.

    Returns the normalised URL (scheme + host [+ port] + path). If the
    caller supplied no path, `/v1/chat/completions` is appended so the
    result is directly usable as an OpenAI-compat chat endpoint.

    Raises ``ValueError`` on any violation. The error message is safe to
    surface to the client — it never echoes back the full URL when a
    secret is involved.
    """
    if not isinstance(url, str) or not url:
        raise ValueError("worker_url must be a non-empty string")

    url = url.strip()
    if len(url) > _MAX_WORKER_URL_LEN:
        raise ValueError(f"worker_url too long (max {_MAX_WORKER_URL_LEN})")

    # Reject any control chars / whitespace mid-URL before parsing.
    for ch in url:
        if ord(ch) < 0x20 or ch in (" ", "\t", "\r", "\n"):
            raise ValueError("worker_url contains whitespace or control characters")

    try:
        parsed = urlparse(url)
    except Exception as exc:  # noqa: BLE001 — urlparse is famously lenient
        raise ValueError("worker_url is not a parseable URL") from exc

    # --- Scheme: HTTPS only, no exceptions (MITM protection) --------------
    if parsed.scheme != "https":
        raise ValueError(
            "worker_url must use the https:// scheme (plain http or other "
            "schemes are rejected to protect against MITM/downgrade attacks)"
        )

    # --- No embedded credentials ------------------------------------------
    if parsed.username or parsed.password:
        raise ValueError("worker_url must not contain embedded credentials")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("worker_url must include a hostname")

    # --- Blocklisted host names -------------------------------------------
    if host in _BLOCKED_WORKER_HOSTS or host.endswith(".localhost"):
        raise ValueError(f"worker_url host '{host}' is not allowed")

    # --- Raw IP? block private/loopback/reserved ranges (SSRF) ------------
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        ip_obj = None

    if ip_obj is not None:
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
            or ip_obj.is_reserved
        ):
            raise ValueError(
                f"worker_url host '{host}' is a private, loopback, "
                "link-local, multicast, or reserved address"
            )
    else:
        # DNS hostname — basic character sanity check.
        if not re.match(r"^[a-z0-9._-]+$", host):
            raise ValueError(f"worker_url host '{host}' contains invalid characters")
        if ".." in host or host.startswith(".") or host.endswith("."):
            raise ValueError(f"worker_url host '{host}' is malformed")
        # Resolve and re-check every answer against the private/reserved ranges.
        # Without this a name like rebind.attacker.com pointing at
        # 169.254.169.254 (cloud metadata) or 127.0.0.1 would sail past the
        # IP-literal block above. (Residual TOCTOU: the outbound request
        # re-resolves later; this raises the bar at config-save time. Resolution
        # failure is left non-fatal — the hardened client + provider allowlist
        # still gate the actual call.)
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            infos = []
        for info in infos:
            resolved = info[4][0]
            try:
                rip = ipaddress.ip_address(resolved)
            except ValueError:
                continue
            if (
                rip.is_private
                or rip.is_loopback
                or rip.is_link_local
                or rip.is_multicast
                or rip.is_unspecified
                or rip.is_reserved
            ):
                raise ValueError(
                    f"worker_url host '{host}' resolves to a private/reserved "
                    f"address ({resolved}) — refusing (SSRF guard)"
                )

    # --- Port sanity ------------------------------------------------------
    port = parsed.port  # urlparse already validates this returns int or None
    if port is not None and (port < 1 or port > 65535):
        raise ValueError(f"worker_url port '{port}' out of range")

    # --- Path normalisation -----------------------------------------------
    path = parsed.path or ""
    if not path or path == "/":
        path = "/v1/chat/completions"

    port_part = f":{port}" if port is not None else ""
    # Query/fragment are intentionally stripped — we never carry arbitrary
    # user-controlled query params into an outbound HTTP request.
    return f"https://{host}{port_part}{path}"


DEFAULT_TIMEOUT = 60.0  # seconds
MAX_TOKENS = 1024
# OpenAI's reasoning models spend hidden reasoning tokens out of the same
# max_completion_tokens budget as the answer, so 1024 can run out before a
# word of the answer is written. It is a ceiling, billed only as used.
REASONING_MAX_TOKENS = 8192
TEMPERATURE = 0.3  # low — we want grounded analysis, not creative writing

_OPENAI_REASONING_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")


def _is_openai_reasoning_model(model: str) -> bool:
    return (model or "").startswith(_OPENAI_REASONING_PREFIXES)


# GPT-6 tool calling through Chat Completions: Sol and Luna accept tools only
# at reasoning_effort "none"; Astra's tool calling requires the Responses API.
_OPENAI_TOOLS_NEED_NO_REASONING = ("gpt-6-sol", "gpt-6-luna")
_OPENAI_TOOLS_NEED_RESPONSES_API = ("gpt-6-astra",)

# OpenAI aliases whose temperature support is undocumented; omitting it sends
# the model's default rather than risking a refused request.
_OPENAI_DEFAULT_TEMPERATURE_ALIASES = ("chat-latest",)

# Claude 4.7 and later refuse a non-default temperature with a 400.
_CLAUDE_VERSION_RE = re.compile(r"^claude-(?:[a-z]+-)?(\d+)(?:-(\d{1,2}))?(?:-|$)")


def _claude_accepts_temperature(model: str) -> bool:
    match = _CLAUDE_VERSION_RE.match(model or "")
    if not match:
        return True
    version = (int(match.group(1)), int(match.group(2) or 0))
    return version < (4, 7)


def _ran_out_of_tokens(body: Dict[str, Any]) -> bool:
    """True when an OpenAI-style reply stopped at the token limit."""
    try:
        return body["choices"][0].get("finish_reason") == "length"
    except (KeyError, IndexError, TypeError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderSpec:
    """Static metadata about a supported AI provider."""

    key: str  # machine id used in settings + UI
    label: str  # human-readable name for the UI
    default_model: str  # recommended default as of September 2026
    wire_format: str  # "openai" | "anthropic" | "gemini"
    docs_url: str  # where users go to get a key
    free_tier_hint: str  # 1-line description for the UI
    # Curated known-good model IDs, shown as a dropdown in the UI. The user
    # can always pick "Custom…" and type a new one when vendors ship things
    # we haven't catalogued yet — these lists rot fast.
    model_choices: tuple = ()
    needs_account_id: bool = False  # Cloudflare direct REST
    needs_worker_url: bool = False  # Self-hosted CF Worker gateway
    needs_endpoint_url: bool = False  # generic OpenAI-compatible endpoint (custom)


PROVIDERS: Dict[str, ProviderSpec] = {
    "grok": ProviderSpec(
        key="grok",
        label="xAI Grok",
        default_model="grok-4.6",
        wire_format="openai",
        docs_url="https://console.x.ai/",
        free_tier_hint="API key required — check xAI Console for current pricing and limits",
        # https://docs.x.ai/developers/models
        model_choices=("grok-4.6", "grok-4.7"),
    ),
    "groq": ProviderSpec(
        key="groq",
        label="Groq (LPU Cloud)",
        default_model="openai/gpt-oss-120b",
        wire_format="openai",
        docs_url="https://console.groq.com/keys",
        free_tier_hint="API key required — check Groq Console for current access and limits",
        # Production text models from https://console.groq.com/docs/models.
        # Custom… remains available for account-specific and future models.
        model_choices=(
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
        ),
    ),
    "cloudflare": ProviderSpec(
        key="cloudflare",
        label="Cloudflare Workers AI (direct)",
        default_model="@cf/openai/gpt-oss-120b",
        wire_format="openai",
        docs_url="https://dash.cloudflare.com/profile/api-tokens",
        free_tier_hint="Cloudflare API token and account ID required",
        needs_account_id=True,
        # Subset of CF's catalogue — full list at
        # https://developers.cloudflare.com/workers-ai/models/
        model_choices=(
            "@cf/openai/gpt-oss-120b",
            "@cf/openai/gpt-oss-20b",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
            "@cf/meta/llama-4-scout-17b-16e-instruct",
        ),
    ),
    "cloudflare_worker": ProviderSpec(
        key="cloudflare_worker",
        label="Cloudflare Worker Gateway (self-hosted)",
        default_model="@cf/openai/gpt-oss-120b",
        wire_format="openai",
        docs_url="https://github.com/pnwimport/slowbooks-pro-2026/tree/main/cloudflare",
        free_tier_hint=(
            "Deploy cloudflare/worker.js in your own CF account — "
            "real API credentials stay in Cloudflare, Slowbooks only "
            "holds a shared secret"
        ),
        needs_worker_url=True,
        model_choices=(
            "@cf/openai/gpt-oss-120b",
            "@cf/openai/gpt-oss-20b",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
            "@cf/meta/llama-4-scout-17b-16e-instruct",
        ),
    ),
    "anthropic": ProviderSpec(
        key="anthropic",
        label="Anthropic Claude",
        default_model="claude-sonnet-5",
        wire_format="anthropic",
        docs_url="https://console.anthropic.com/",
        free_tier_hint="API key required — check Anthropic Console for current access",
        model_choices=(
            "claude-sonnet-5",
            "claude-opus-5-5",
            "claude-fable-5-1",
            "claude-opus-5",
            "claude-fable-5",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ),
    ),
    "openai": ProviderSpec(
        key="openai",
        label="OpenAI",
        default_model="gpt-5.6-terra",
        wire_format="openai",
        docs_url="https://platform.openai.com/api-keys",
        free_tier_hint="API key and API billing account required",
        # Current general-purpose Chat Completions models. Custom… supports
        # account-specific snapshots and future IDs without an app release.
        model_choices=(
            "gpt-5.6-terra",
            "gpt-5.6-sol",
            "gpt-5.6-luna",
            "gpt-6-sol",
            "gpt-6-luna",
            "chat-latest",
        ),
    ),
    "gemini": ProviderSpec(
        key="gemini",
        label="Google Gemini",
        default_model="gemini-3.8-flash",
        wire_format="gemini",
        docs_url="https://aistudio.google.com/app/apikey",
        free_tier_hint="API key required — check AI Studio for current access and limits",
        model_choices=(
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
        ),
    ),
    "custom": ProviderSpec(
        key="custom",
        label="Custom (OpenAI-compatible)",
        default_model="",  # user supplies the model ID
        wire_format="openai",
        docs_url="",
        free_tier_hint=(
            "Point Slowbooks at any OpenAI-compatible chat endpoint on the "
            "public internet. Paste the base URL (e.g. https://api.example.com/v1) — "
            "/chat/completions is appended automatically. HTTPS only; "
            "localhost, LAN and other private addresses are refused (SSRF guard), "
            "so a model running on this machine needs a public HTTPS front."
        ),
        needs_endpoint_url=True,
        model_choices=(),
    ),
}


def provider_list() -> list:
    """Return provider metadata in a UI-friendly shape (no secrets)."""
    return [
        {
            "key": p.key,
            "label": p.label,
            "default_model": p.default_model,
            "model_choices": list(p.model_choices),
            "docs_url": p.docs_url,
            "free_tier_hint": p.free_tier_hint,
            "needs_account_id": p.needs_account_id,
            "needs_worker_url": p.needs_worker_url,
            "needs_endpoint_url": p.needs_endpoint_url,
        }
        for p in PROVIDERS.values()
    ]


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = (
    "You are a senior financial analyst reviewing a small business's "
    "bookkeeping snapshot. Your job is to produce a short, actionable "
    "executive brief using ONLY the numbers in the data provided. "
    "Do not make up figures. Be specific — cite customer names, account "
    "codes, and dollar amounts from the data. Keep the total response "
    "under 400 words. Format as three sections: Observations, Risks, "
    "Recommendations. Use 3 bullet points per section."
)


def _top_agers(aging: Dict[str, Dict[str, float]], n: int = 3) -> list:
    """Return the top N names from an aging dict sorted by total balance."""
    totals = {}
    for bucket, by_name in (aging or {}).items():
        for name, amount in (by_name or {}).items():
            totals[name] = totals.get(name, 0.0) + float(amount or 0)
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:n]


def build_insights_prompt(dashboard: Dict[str, Any], company_name: str = "") -> str:
    """Turn a dashboard dict into a structured analyst prompt."""
    revenue_by_customer = dashboard.get("revenue_by_customer", {}) or {}
    expenses_by_category = dashboard.get("expenses_by_category", {}) or {}
    revenue_trend = dashboard.get("revenue_trend", {}) or {}
    ar_aging = dashboard.get("ar_aging", {}) or {}
    ap_aging = dashboard.get("ap_aging", {}) or {}
    cash_forecast = dashboard.get("cash_forecast", []) or []
    dso = dashboard.get("dso", 0) or 0

    total_revenue = sum(float(v or 0) for v in revenue_by_customer.values())
    total_expenses = sum(float(v or 0) for v in expenses_by_category.values())
    margin_pct = (
        ((total_revenue - total_expenses) / total_revenue) * 100
        if total_revenue > 0
        else 0
    )
    net_income = total_revenue - total_expenses

    # Top revenue customers
    top_customers = sorted(
        revenue_by_customer.items(), key=lambda kv: kv[1], reverse=True
    )[:5]
    # Top expense categories
    top_expenses = sorted(
        expenses_by_category.items(), key=lambda kv: kv[1], reverse=True
    )[:5]
    # Top agers
    worst_ar = _top_agers(ar_aging, 3)
    worst_ap = _top_agers(ap_aging, 3)

    # 90-day forecast summary — first, middle, last buckets
    forecast_summary = ""
    if cash_forecast:
        first = cash_forecast[0]
        last = cash_forecast[-1]
        forecast_summary = (
            f"90-day forecast: starting at ${first.get('net', 0):,.0f} net "
            f"(collections ${first.get('collections', 0):,.0f} − "
            f"payments ${first.get('payments', 0):,.0f}), "
            f"ending at ${last.get('net', 0):,.0f} net."
        )

    # Revenue trend line
    trend_lines = [
        f"  {month}: ${float(val or 0):,.0f}"
        for month, val in list(revenue_trend.items())[-6:]  # last 6 months
    ]

    period = dashboard.get("period", {}) or {}
    period_label = (
        f"{period.get('name', 'month').upper()} "
        f"({period.get('start', '?')} → {period.get('end', '?')})"
        if period
        else "(unspecified window)"
    )

    company = company_name or "the business"

    lines = [
        f"Financial snapshot for {company} — {period_label}",
        "",
        "=== KEY METRICS ===",
        f"Revenue:     ${total_revenue:,.0f}",
        f"Expenses:    ${total_expenses:,.0f}",
        f"Net income:  ${net_income:,.0f}",
        f"Margin:      {margin_pct:.1f}%",
        f"DSO:         {float(dso):.1f} days",
        "",
        "=== TOP REVENUE CUSTOMERS ===",
    ]
    lines += [f"  {name}: ${float(amt or 0):,.0f}" for name, amt in top_customers] or [
        "  (none)"
    ]

    lines += ["", "=== TOP EXPENSE CATEGORIES ==="]
    lines += [f"  {cat}: ${float(amt or 0):,.0f}" for cat, amt in top_expenses] or [
        "  (none)"
    ]

    lines += ["", "=== RECENT REVENUE TREND (last 6 months) ==="]
    lines += trend_lines or ["  (no data)"]

    lines += ["", "=== ACCOUNTS RECEIVABLE (worst outstanding balances) ==="]
    lines += [f"  {name}: ${amt:,.0f} open" for name, amt in worst_ar] or [
        "  (nothing outstanding)"
    ]

    lines += ["", "=== ACCOUNTS PAYABLE (worst outstanding balances) ==="]
    lines += [f"  {name}: ${amt:,.0f} open" for name, amt in worst_ap] or [
        "  (nothing outstanding)"
    ]

    if forecast_summary:
        lines += ["", "=== CASH FORECAST ===", f"  {forecast_summary}"]

    lines += [
        "",
        "Produce the analyst brief now. Use only the numbers above.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provider adapters — each returns a dict with method/url/headers/json
# ---------------------------------------------------------------------------


def _openai_style_request(
    url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    *,
    token_parameter: str = "max_tokens",
    openai_native: bool = False,
) -> Dict[str, Any]:
    """Build an OpenAI-compatible chat-completions request.

    Shared by OpenAI, Grok, Groq, and Cloudflare (all OpenAI-compat endpoints).
    """
    reasoning = openai_native and _is_openai_reasoning_model(model)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_completion_tokens" if openai_native else token_parameter: (
            REASONING_MAX_TOKENS if reasoning else MAX_TOKENS
        ),
    }
    # Reasoning models can reject temperature; omitting it uses the model's
    # default and keeps the request valid if its reasoning effort changes.
    if not reasoning and not (
        openai_native and model in _OPENAI_DEFAULT_TEMPERATURE_ALIASES
    ):
        body["temperature"] = TEMPERATURE
    return {
        "method": "POST",
        "url": url,
        "headers": {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        "json": body,
    }


# ---------------------------------------------------------------------------
# Outbound URL allowlist (defense-in-depth + CodeQL trust boundary)
# ---------------------------------------------------------------------------

# Per-provider hardcoded URL prefixes. The cloudflare_worker provider is the
# only one whose URL is user-supplied; that one runs through
# validate_worker_url() and is re-validated here at call time.
_PROVIDER_URL_PREFIXES = {
    "grok": "https://api.x.ai/",
    "groq": "https://api.groq.com/",
    "openai": "https://api.openai.com/",
    "anthropic": "https://api.anthropic.com/",
    "gemini": "https://generativelanguage.googleapis.com/",
    "cloudflare": "https://api.cloudflare.com/",
    # cloudflare_worker has no static prefix — see _check_outbound_url
}


def _check_outbound_url(provider_key: str, url: str) -> str:
    """Last-line allowlist on the outbound HTTP URL.

    `build_request()` already constructs URLs from validated inputs, but
    re-validating here:
      1. Acts as defense-in-depth — a future regression in build_request
         can't accidentally let a user-controlled URL through.
      2. Gives static analyzers (CodeQL) a clear trust boundary right at
         the network sink, instead of having to trace through helpers.

    Returns the URL unchanged on success; raises AIProviderError otherwise.
    """
    if not isinstance(url, str) or not url:
        raise AIProviderError(f"{provider_key}: empty outbound URL")

    if provider_key in ("cloudflare_worker", "custom"):
        # Return the value validate_worker_url() produces (it returns the
        # normalized URL on success, raises on failure). Using the return
        # value rather than the input also gives static analyzers a clear
        # validated-string source they can trace.
        return validate_worker_url(url)

    prefix = _PROVIDER_URL_PREFIXES.get(provider_key)
    if not prefix:
        raise AIProviderError(f"{provider_key}: unknown provider")
    if not url.startswith(prefix):
        raise AIProviderError(f"{provider_key}: outbound URL not on allowlist")
    # Return the matched-prefix URL via concatenation so static analyzers
    # see the value as derived from a hardcoded constant + the suffix.
    return prefix + url[len(prefix) :]


def build_request(
    provider_key: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    account_id: Optional[str] = None,
    worker_url: Optional[str] = None,
    endpoint_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an httpx-ready request dict for the given provider.

    Separated from the network call so unit tests can verify the exact
    URL / headers / body without mocking httpx.
    """
    if provider_key not in PROVIDERS:
        raise ValueError(f"Unknown AI provider: {provider_key}")
    spec = PROVIDERS[provider_key]
    model = model or spec.default_model

    if provider_key == "grok":
        return _openai_style_request(
            "https://api.x.ai/v1/chat/completions",
            api_key,
            model,
            system,
            user,
        )

    if provider_key == "groq":
        return _openai_style_request(
            "https://api.groq.com/openai/v1/chat/completions",
            api_key,
            model,
            system,
            user,
            token_parameter="max_completion_tokens",
        )

    if provider_key == "openai":
        return _openai_style_request(
            "https://api.openai.com/v1/chat/completions",
            api_key,
            model,
            system,
            user,
            openai_native=True,
        )

    if provider_key == "cloudflare":
        if not account_id:
            raise ValueError("Cloudflare Workers AI requires an account_id")
        if not CLOUDFLARE_ACCOUNT_ID_RE.match(account_id):
            raise ValueError(
                "cloudflare_account_id must be exactly 32 lowercase hex characters"
            )
        url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{account_id}/ai/v1/chat/completions"
        )
        return _openai_style_request(url, api_key, model, system, user)

    if provider_key == "cloudflare_worker":
        # Self-hosted CF Worker (see cloudflare/worker.js). The user runs
        # their own Worker in their own Cloudflare account; Slowbooks only
        # holds the shared Bearer secret. URL is validated aggressively by
        # validate_worker_url() to prevent MITM / SSRF / scheme confusion.
        if not worker_url:
            raise ValueError(
                "Cloudflare Worker gateway requires worker_url — deploy "
                "cloudflare/worker.js and paste its URL in AI settings"
            )
        safe_url = validate_worker_url(worker_url)
        return _openai_style_request(safe_url, api_key, model, system, user)

    if provider_key == "custom":
        # Generic OpenAI-compatible endpoint. The base URL is user-supplied
        # and validated aggressively (https only, no private/loopback IPs,
        # no embedded credentials — see validate_worker_url). We append
        # /chat/completions to the normalized base so the user can paste
        # either the bare origin or a /v1-style base.
        if not endpoint_url:
            raise ValueError(
                "Custom provider requires endpoint_url — paste the OpenAI-"
                "compatible base URL in AI settings"
            )
        safe_url = validate_worker_url(endpoint_url)
        if not safe_url.rstrip("/").endswith("/chat/completions"):
            safe_url = safe_url.rstrip("/") + "/chat/completions"
        return _openai_style_request(safe_url, api_key, model, system, user)

    if provider_key == "anthropic":
        body = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if _claude_accepts_temperature(model):
            body["temperature"] = TEMPERATURE
        return {
            "method": "POST",
            "url": "https://api.anthropic.com/v1/messages",
            "headers": {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            "json": body,
        }

    if provider_key == "gemini":
        # Gemini takes the API key as a URL query param (!) and has its own
        # request/response shape with role: "user" and parts: [{text: ...}].
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        return {
            "method": "POST",
            "url": url,
            "headers": {"Content-Type": "application/json"},
            "json": {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [
                    {"role": "user", "parts": [{"text": user}]},
                ],
                "generationConfig": {
                    "temperature": TEMPERATURE,
                    "maxOutputTokens": MAX_TOKENS,
                },
            },
        }

    raise ValueError(f"Unhandled AI provider: {provider_key}")


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_response(provider_key: str, body: Dict[str, Any]) -> str:
    """Extract the assistant's text from a provider response body.

    Each API puts the text in a different spot; we normalise here.
    Returns an empty string on parse failure — the caller decides
    whether to treat that as an error.
    """
    if not isinstance(body, dict):
        return ""
    if provider_key in (
        "grok",
        "groq",
        "openai",
        "cloudflare",
        "cloudflare_worker",
        "custom",
    ):
        try:
            text = body["choices"][0]["message"]["content"]
            return text if isinstance(text, str) else ""
        except (KeyError, IndexError, TypeError):
            return ""

    if provider_key == "anthropic":
        try:
            # content is a list of blocks; we want the first text block
            blocks = body.get("content") or []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    return text if isinstance(text, str) else ""
            return ""
        except (KeyError, TypeError):
            return ""

    if provider_key == "gemini":
        try:
            parts = body["candidates"][0]["content"]["parts"]
            # Gemini parts are a list; concatenate any text fields.
            return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        except (KeyError, IndexError, TypeError):
            return ""

    return ""


# ---------------------------------------------------------------------------
# Network call
# ---------------------------------------------------------------------------


class AIProviderError(Exception):
    """Raised when the AI provider returns a non-2xx or malformed response."""


def _hardened_client(timeout: float) -> httpx.Client:
    """Build an httpx.Client with explicit security defaults.

    Every outbound AI call goes through one of these so the security
    posture is obvious from the code (not implicit httpx defaults):

      * ``verify=True``        — TLS cert validation on; no downgrade
      * ``follow_redirects=False`` — a compromised upstream can't 302 us
        into a different host/scheme (e.g. cleartext or an SSRF target)
      * explicit timeout       — no hang forever on a dead provider
      * minimal User-Agent     — don't leak version strings
    """
    return httpx.Client(
        timeout=timeout,
        verify=True,
        follow_redirects=False,
        headers={"User-Agent": "slowbooks-pro-ai/1.0"},
        trust_env=False,
    )


def _resolve_public_endpoint(url: str) -> str:
    """Resolve a user-configured endpoint and return one checked address."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise AIProviderError("AI endpoint hostname could not be resolved") from exc
    if not infos:
        raise AIProviderError("AI endpoint hostname could not be resolved")
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError, TypeError) as exc:
            raise AIProviderError("AI endpoint returned an invalid address") from exc
        if not address.is_global:
            raise AIProviderError(
                "AI endpoint resolves to a private or local address — refusing"
            )
    return infos[0][4][0]


def _pin_public_endpoint(url: str, address: str) -> tuple[str, dict]:
    """Connect to the checked address while preserving Host and TLS SNI."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    ip = ipaddress.ip_address(address)
    netloc = f"[{address}]" if ip.version == 6 else address
    if parts.port:
        netloc += f":{parts.port}"
    pinned = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return pinned, {"host": parts.netloc, "sni": host}


def _response_peer_address(response: httpx.Response) -> Optional[str]:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return None
    try:
        info = stream.get_extra_info("server_addr")
        address = info[0]
        ipaddress.ip_address(address)
    except (OSError, ValueError, AttributeError, IndexError, TypeError):
        return None
    return address


def _execute_request(
    provider_key: str,
    req: Dict[str, Any],
    timeout: float,
    client: Optional[httpx.Client],
) -> httpx.Response:
    """Execute one provider request with endpoint pinning where required."""
    safe_url = _check_outbound_url(provider_key, req["url"])
    if client is not None:
        # Injectable clients are deterministic test transports and perform no
        # production network I/O. Production calls always use the path below.
        return client.request(
            req["method"], safe_url, headers=req["headers"], json=req["json"]
        )

    if provider_key in ("cloudflare_worker", "custom"):
        address = _resolve_public_endpoint(safe_url)
        pinned_url, names = _pin_public_endpoint(safe_url, address)
        headers = {**req["headers"], "Host": names["host"]}
        with _hardened_client(timeout) as hardened:
            response = hardened.request(
                req["method"],
                pinned_url,
                headers=headers,
                json=req["json"],
                extensions={"sni_hostname": names["sni"]},
            )
            peer = _response_peer_address(response)
        if peer and not ipaddress.ip_address(peer).is_global:
            raise AIProviderError(
                "AI endpoint connected to a private or local address — refusing"
            )
        return response

    with _hardened_client(timeout) as hardened:
        return hardened.request(
            req["method"], safe_url, headers=req["headers"], json=req["json"]
        )


def call_provider(
    provider_key: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    account_id: Optional[str] = None,
    worker_url: Optional[str] = None,
    endpoint_url: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    client: Optional[httpx.Client] = None,
) -> str:
    """Make the HTTP call and return the assistant's text.

    `client` is injectable for tests that want to stub out the transport.
    """
    req = build_request(
        provider_key,
        api_key,
        model,
        system,
        user,
        account_id,
        worker_url,
        endpoint_url,
    )
    try:
        resp = _execute_request(provider_key, req, timeout, client)
    except httpx.HTTPError as e:
        # Never include api_key in the exception — it might have been
        # substituted into the URL (Gemini).
        raise AIProviderError(f"{provider_key}: network error") from e

    if resp.status_code >= 400:
        # Surface the provider's error message (minus any echoed keys)
        # to the caller so the UI can show something useful.
        text = resp.text
        if api_key and api_key in text:
            text = text.replace(api_key, "***REDACTED***")
        raise AIProviderError(f"{provider_key}: HTTP {resp.status_code} — {text[:500]}")

    try:
        body = resp.json()
    except ValueError as e:
        raise AIProviderError(f"{provider_key}: non-JSON response") from e

    text = parse_response(provider_key, body)
    if not text and _ran_out_of_tokens(body):
        raise AIProviderError(
            f"{provider_key}: the model reached its output limit before writing an "
            "answer. Try again, or pick a smaller or non-reasoning model."
        )
    if not text:
        raise AIProviderError(f"{provider_key}: empty response (body shape unexpected)")
    return text


def generate_insights(
    provider_key: str,
    api_key: str,
    model: str,
    dashboard: Dict[str, Any],
    company_name: str = "",
    account_id: Optional[str] = None,
    worker_url: Optional[str] = None,
    endpoint_url: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """End-to-end: build prompt, call provider, return structured result."""
    prompt = build_insights_prompt(dashboard, company_name)
    text = call_provider(
        provider_key=provider_key,
        api_key=api_key,
        model=model,
        system=SYSTEM_PROMPT,
        user=prompt,
        account_id=account_id,
        worker_url=worker_url,
        endpoint_url=endpoint_url,
        client=client,
    )
    return {
        "insights": text,
        "provider": provider_key,
        "provider_label": PROVIDERS[provider_key].label,
        "model": model or PROVIDERS[provider_key].default_model,
        "generated_at": date.today().isoformat(),
    }


# ---------------------------------------------------------------------------
# Tool-calling / function-calling loop (Phase 9.5b)
# Supports OpenAI, Anthropic, and Gemini wire formats with max 8 iterations
# ---------------------------------------------------------------------------


def call_with_tools(
    provider_key: str,
    api_key: str,
    model: str,
    user_question: str,
    tools: Dict[str, Any],
    tool_executor,
    account_id: Optional[str] = None,
    worker_url: Optional[str] = None,
    endpoint_url: Optional[str] = None,
    max_calls: int = 8,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """
    Execute a tool-calling loop against an LLM that supports function calling.

    Takes a user question, gets the LLM to call tools, executes them, feeds
    results back to the LLM, repeats until the LLM responds with text (no
    more tool calls) or max_calls is hit.

    Args:
        provider_key: "grok" | "groq" | "openai" | "cloudflare" | "anthropic" | "gemini"
        api_key: Provider's API key
        model: Model identifier
        user_question: The user's query
        tools: Dict of {tool_name: {name, description, parameters, ...}}
        tool_executor: Callable(tool_name, **kwargs) -> dict result
        account_id: For Cloudflare (optional)
        max_calls: Max tool call iterations (default 8)
        client: httpx.Client for testing (optional)

    Returns:
        {
            "provider": str,
            "model": str,
            "final_response": str,
            "tool_calls": [{tool_name, params, result}, ...],
            "call_count": int,
            "success": bool,
        }
    """
    spec = PROVIDERS.get(provider_key)
    if not spec:
        raise ValueError(f"Unknown provider: {provider_key}")

    wire_format = spec.wire_format
    if provider_key == "openai" and (model or "").startswith(
        _OPENAI_TOOLS_NEED_RESPONSES_API
    ):
        raise AIProviderError(
            f"openai: {model} answers tool-based questions only through the "
            "Responses API; choose gpt-6-sol or gpt-6-luna for Ask SlowBooks"
        )
    messages = [{"role": "user", "content": user_question}]
    gemini_contents = [{"role": "user", "parts": [{"text": user_question}]}]
    tool_calls_made = []
    iteration = 0

    while iteration < max_calls:
        iteration += 1

        # Build the request with tools included
        if wire_format == "openai":
            # OpenAI format: include tools in the request
            req = build_request(
                provider_key,
                api_key,
                model,
                "",
                user_question,
                account_id,
                worker_url,
                endpoint_url,
            )
            req["json"]["messages"] = messages
            req["json"]["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {}),
                    },
                }
                for tool in tools.values()
            ]
            if provider_key == "openai" and (model or "").startswith(
                _OPENAI_TOOLS_NEED_NO_REASONING
            ):
                req["json"]["reasoning_effort"] = "none"

        elif wire_format == "anthropic":
            # Anthropic format: tools at top level
            req = build_request(
                provider_key,
                api_key,
                model,
                "",
                user_question,
                account_id,
                worker_url,
                endpoint_url,
            )
            req["json"]["messages"] = messages
            req["json"]["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": {
                        "type": "object",
                        "properties": tool.get("parameters", {}).get("properties", {}),
                        "required": tool.get("parameters", {}).get("required", []),
                    },
                }
                for tool in tools.values()
            ]

        elif wire_format == "gemini":
            # Gemini has a different tool format
            req = build_request(
                provider_key,
                api_key,
                model,
                "",
                user_question,
                account_id,
                worker_url,
                endpoint_url,
            )
            req["json"]["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": {
                                "type": "object",
                                "properties": tool.get("parameters", {}).get(
                                    "properties", {}
                                ),
                            },
                        }
                        for tool in tools.values()
                    ]
                }
            ]
            req["json"]["contents"] = gemini_contents
            if "messages" in req["json"]:
                del req["json"]["messages"]
        else:
            raise ValueError(
                f"Tool calling not supported for wire format: {wire_format}"
            )

        # Make the call — reuses the same hardened-client profile as
        # call_provider (verify=True, follow_redirects=False, explicit UA).
        try:
            resp = _execute_request(provider_key, req, DEFAULT_TIMEOUT, client)
        except httpx.HTTPError as e:
            raise AIProviderError(f"{provider_key}: network error") from e

        if resp.status_code >= 400:
            text = resp.text
            if api_key and api_key in text:
                text = text.replace(api_key, "***REDACTED***")
            raise AIProviderError(
                f"{provider_key}: HTTP {resp.status_code} — {text[:500]}"
            )

        try:
            body = resp.json()
        except ValueError as e:
            raise AIProviderError(f"{provider_key}: non-JSON response") from e

        # Parse response and check for tool calls
        tool_calls = _extract_tool_calls(wire_format, body)

        if not tool_calls:
            # No tool calls — LLM is done. Extract final text.
            final_text = parse_response(provider_key, body)
            return {
                "provider": provider_key,
                "model": model,
                "final_response": final_text,
                "tool_calls": tool_calls_made,
                "call_count": iteration,
                "success": bool(final_text),
            }

        # Execute all calls from this assistant turn before adding protocol
        # history. OpenAI and Anthropic require the original provider-issued
        # call IDs to be echoed with the corresponding results.
        executed_calls = []
        for call in tool_calls:
            tool_name = call.get("name")
            tool_params = call.get("arguments", {})
            result = tool_executor(tool_name, **tool_params)
            executed_calls.append((call, tool_name, tool_params, result))
            tool_calls_made.append(
                {
                    "tool_name": tool_name,
                    "params": tool_params,
                    "result": result,
                }
            )

        if wire_format == "openai":
            assistant_calls = []
            completed_before = len(tool_calls_made) - len(executed_calls)
            for index, (call, tool_name, tool_params, _result) in enumerate(
                executed_calls, start=1
            ):
                call_id = call.get("id") or f"call_{completed_before + index}"
                assistant_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": call.get("raw_arguments")
                            or json.dumps(tool_params, default=str),
                        },
                    }
                )
            messages.append(
                {"role": "assistant", "content": None, "tool_calls": assistant_calls}
            )
            for assistant_call, executed in zip(assistant_calls, executed_calls):
                _call, _name, _params, result = executed
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": assistant_call["id"],
                        "content": json.dumps(result, default=str),
                    }
                )

        elif wire_format == "anthropic":
            assistant_content = []
            result_content = []
            completed_before = len(tool_calls_made) - len(executed_calls)
            for index, (call, tool_name, tool_params, result) in enumerate(
                executed_calls, start=1
            ):
                call_id = call.get("id") or f"tool_use_{completed_before + index}"
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": tool_name,
                        "input": tool_params,
                    }
                )
                result_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": json.dumps(result, default=str),
                    }
                )
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": result_content})

        elif wire_format == "gemini":
            gemini_contents.append(
                {
                    "role": "model",
                    "parts": [
                        {"functionCall": {"name": name, "args": params}}
                        for _call, name, params, _result in executed_calls
                    ],
                }
            )
            gemini_contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": name,
                                "response": (
                                    result
                                    if isinstance(result, dict)
                                    else {"result": result}
                                ),
                            }
                        }
                        for _call, name, _params, result in executed_calls
                    ],
                }
            )

    # Max iterations reached
    return {
        "provider": provider_key,
        "model": model,
        "final_response": "Max tool calls reached without final response",
        "tool_calls": tool_calls_made,
        "call_count": iteration,
        "success": False,
    }


def _extract_tool_calls(wire_format: str, body: Dict[str, Any]) -> list:
    """Extract tool calls from the provider's response body.

    Returns normalized calls, including provider call IDs where applicable.
    """
    if not isinstance(body, dict):
        return []
    if wire_format in ("grok", "groq", "openai", "cloudflare"):
        # OpenAI format: choices[0].message.tool_calls
        try:
            choice = body.get("choices", [{}])[0]
            message = choice.get("message", {})
            return [
                {
                    "id": tc.get("id"),
                    "name": tc.get("function", {}).get("name"),
                    "arguments": _parse_json_args(
                        tc.get("function", {}).get("arguments", "{}")
                    ),
                    "raw_arguments": tc.get("function", {}).get("arguments", "{}"),
                }
                for tc in message.get("tool_calls", [])
            ]
        except (AttributeError, KeyError, IndexError, TypeError):
            return []

    elif wire_format == "anthropic":
        # Anthropic format: content array with type: tool_use blocks
        try:
            content = body.get("content", [])
            return [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "arguments": c.get("input", {}),
                }
                for c in content
                if isinstance(c, dict) and c.get("type") == "tool_use"
            ]
        except (KeyError, TypeError):
            return []

    elif wire_format == "gemini":
        # Gemini format: candidates[0].content.parts with functionCall
        try:
            candidate = body.get("candidates", [{}])[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            return [
                {
                    "name": p.get("functionCall", {}).get("name"),
                    "arguments": p.get("functionCall", {}).get("args", {}),
                }
                for p in parts
                if isinstance(p, dict) and "functionCall" in p
            ]
        except (AttributeError, KeyError, IndexError, TypeError):
            return []

    return []


def _parse_json_args(args_str: str) -> Dict[str, Any]:
    """Parse JSON arguments string (from OpenAI format)."""
    if isinstance(args_str, dict):
        return args_str
    try:
        return json.loads(args_str)
    except (ValueError, TypeError):
        return {}
