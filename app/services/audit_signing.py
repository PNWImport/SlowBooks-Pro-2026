# ============================================================================
# Signing for audit checkpoints — HMAC-SHA256 under an operator-held key.
# ----------------------------------------------------------------------------
# WHY THIS EXISTS. `document_audits` is a linked hash chain, so alteration,
# deletion and reordering all break it. `audit_checkpoints` pins the tip so
# truncation of the tail is detectable too. But a checkpoint row stored in the
# same database an attacker can write is evidence, not proof: delete the rows
# AND the checkpoints and nothing internal notices.
#
# Signing closes part of that, and off-box export closes the rest:
#
#   * A signature over the checkpoint tuple means an attacker with DATABASE
#     write access — SQL injection, stolen DB credentials, a restored backup,
#     a rogue DBA — cannot forge a checkpoint. They can delete one, but they
#     cannot mint a replacement that attests to the truncated state.
#
#   * An exported artifact (see document_audit.export_checkpoint) carries the
#     payload and its signature, so the operator can keep it on WORM storage
#     or a second system and later verify it against the live database with
#     no checkpoint row present at all.
#
# WHAT IT DOES NOT DO, stated plainly. This is a symmetric MAC: the key that
# verifies is the key that signs. An attacker who owns the APPLICATION host
# reads the key out of the environment and can sign whatever they like. The
# defence against that is the off-box copy — an artifact already written to
# append-only storage cannot be retroactively changed — not the MAC itself.
# A true asymmetric signature (sign on the app host, verify with a public key
# anywhere) would let a third party verify without holding signing power; that
# is a bigger key-management story and is not what this implements.
#
# CONFIGURATION.
#
#   AUDIT_CHECKPOINT_SIGNING_SECRET       — current key. Signs and verifies.
#   AUDIT_CHECKPOINT_SIGNING_SECRET_PREV  — optional, verify-only, for rotation.
#   AUDIT_CHECKPOINT_KEY_ID               — label stored on the row so an
#                                           auditor knows which key to use.
#                                           Defaults to "primary".
#
# There is deliberately NO development default and no fallback to
# PAYROLL_ENCRYPTION_SECRET. A signature under a well-known key is worse than
# no signature, because it looks like proof. With nothing configured,
# checkpoints are created unsigned and every verification says so loudly.
#
# Rotation:
#   1. Move the live secret to AUDIT_CHECKPOINT_SIGNING_SECRET_PREV.
#   2. Set the new secret as AUDIT_CHECKPOINT_SIGNING_SECRET, new label as
#      AUDIT_CHECKPOINT_KEY_ID.
#   3. Bounce the app. Old checkpoints verify as `valid_previous_key`.
#   4. `python -m app.services.document_audit resign` re-signs them.
#   5. Drop AUDIT_CHECKPOINT_SIGNING_SECRET_PREV.
# ============================================================================

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any

from app import config

ALGORITHM = "HMAC-SHA256"

# Version tag inside the signed payload. Bump if the payload's meaning changes
# so an old artifact can never be reinterpreted under new rules.
PAYLOAD_VERSION = "sbcp1"

# Keys the payload must carry to be signable/verifiable at all.
REQUIRED_PAYLOAD_KEYS = (
    "v",
    "tip_audit_id",
    "tip_chain_hash",
    "row_count",
    "created_at",
)


def _env(name: str, fallback: str) -> str:
    """Read a signing secret, preferring the live environment.

    config.py loads .env at import, so the config value is the deployed
    setting. Reading os.environ first means a rotation performed by changing
    the process environment takes effect without editing config, and lets
    tests set keys without reloading the module.
    """
    value = os.environ.get(name)
    return (value if value is not None else fallback).strip()


def current_key() -> tuple[str, str] | None:
    """(key_id, secret) for signing, or None when signing is unconfigured."""
    secret = _env(
        "AUDIT_CHECKPOINT_SIGNING_SECRET", config.AUDIT_CHECKPOINT_SIGNING_SECRET
    )
    if not secret:
        return None
    key_id = (
        _env("AUDIT_CHECKPOINT_KEY_ID", config.AUDIT_CHECKPOINT_KEY_ID) or "primary"
    )
    return key_id, secret


def previous_key() -> tuple[str, str] | None:
    """(key_id, secret) for the rotated-out key, verify-only."""
    secret = _env(
        "AUDIT_CHECKPOINT_SIGNING_SECRET_PREV",
        config.AUDIT_CHECKPOINT_SIGNING_SECRET_PREV,
    )
    if not secret:
        return None
    current = current_key()
    if current and secret == current[1]:
        return None
    return "previous", secret


def signing_configured() -> bool:
    return current_key() is not None


def _iso(value) -> str:
    """Stable timestamp rendering. Naive datetimes are read as UTC, matching
    services.document_audit._iso — SQLite hands back naive values."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def build_payload(
    *,
    tip_audit_id: int,
    tip_chain_hash: str,
    row_count: int,
    created_at,
    note: str | None = None,
) -> dict:
    """The tuple a signature commits to.

    `note` is included on purpose: an operator's "FY2026 Q3 close" label is
    part of what the checkpoint asserts, so editing it must break the
    signature. `created_at` is inside too, so a checkpoint cannot be
    back-dated to cover rows it never saw.
    """
    return {
        "v": PAYLOAD_VERSION,
        "tip_audit_id": int(tip_audit_id),
        "tip_chain_hash": tip_chain_hash or "",
        "row_count": int(row_count),
        "created_at": _iso(created_at),
        "note": note or "",
    }


def canonical_bytes(payload: dict) -> bytes:
    """Exactly what gets MAC'd.

    Sorted keys and tight separators, so an offline verifier reproduces the
    bytes from the artifact's own `payload` object with two lines of Python:

        json.dumps(payload, sort_keys=True, separators=(",", ":"))
        hmac.new(key, that.encode(), hashlib.sha256).hexdigest()

    Any key present in the dict is signed, including ones this version does
    not know about — so a newer artifact still verifies here.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _mac(secret: str, payload: dict) -> str:
    return hmac.new(
        secret.encode("utf-8"), canonical_bytes(payload), hashlib.sha256
    ).hexdigest()


def sign(payload: dict) -> dict | None:
    """Sign a payload. Returns None when no signing key is configured.

    Callers must treat None as "unsigned", not as an error — an operator who
    has not set up a signing key still gets working checkpoints, just without
    this protection.
    """
    key = current_key()
    if key is None:
        return None
    key_id, secret = key
    return {
        "signature": _mac(secret, payload),
        "signature_key_id": key_id,
        "signature_algorithm": ALGORITHM,
    }


def payload_problems(payload: Any) -> list[str]:
    """Shape validation for a payload arriving from outside (an artifact)."""
    if not isinstance(payload, dict):
        return ["payload is not an object"]
    problems = [
        f"payload is missing {k}" for k in REQUIRED_PAYLOAD_KEYS if k not in payload
    ]
    if payload.get("v") not in (None, PAYLOAD_VERSION) and "v" in payload:
        problems.append(
            f"payload version {payload['v']!r} is not understood by this "
            f"build (expected {PAYLOAD_VERSION!r})"
        )
    for numeric in ("tip_audit_id", "row_count"):
        if numeric in payload and not isinstance(payload[numeric], int):
            problems.append(f"{numeric} must be an integer")
    return problems


def verify(payload: dict, signature: str | None) -> dict:
    """Check a signature over `payload`.

    Distinguishes five outcomes, because they mean very different things to
    an auditor:

      unsigned            no signature was stored — nothing to check. Not a
                          failure of this checkpoint, a gap in setup.
      unverifiable        a signature exists but no key is configured here,
                          so this box cannot judge it either way.
      valid               matches under the current key.
      valid_previous_key  matches under the rotated-out key. Genuine, but
                          re-sign it before dropping that key.
      invalid             a signature exists and matches no configured key —
                          the payload was altered or the signature forged.

    `ok` is True only for the two valid states. `unsigned` and `unverifiable`
    are deliberately not ok: "we cannot tell" must never read as "verified".
    """
    if not signature:
        return {
            "status": "unsigned",
            "ok": False,
            "algorithm": None,
            "key_id": None,
            "detail": (
                "no signature stored — set AUDIT_CHECKPOINT_SIGNING_SECRET so "
                "future checkpoints cannot be forged by database write access"
            ),
        }

    candidates = [k for k in (current_key(), previous_key()) if k is not None]
    if not candidates:
        return {
            "status": "unverifiable",
            "ok": False,
            "algorithm": ALGORITHM,
            "key_id": None,
            "detail": (
                "a signature is stored but AUDIT_CHECKPOINT_SIGNING_SECRET is "
                "not configured here — this host cannot verify it"
            ),
        }

    for index, (key_id, secret) in enumerate(candidates):
        if hmac.compare_digest(_mac(secret, payload), signature):
            rotated = index > 0
            return {
                "status": "valid_previous_key" if rotated else "valid",
                "ok": True,
                "algorithm": ALGORITHM,
                "key_id": key_id,
                "detail": (
                    "verifies under the rotated-out key — re-sign before "
                    "dropping AUDIT_CHECKPOINT_SIGNING_SECRET_PREV"
                    if rotated
                    else "verifies under the current signing key"
                ),
            }

    return {
        "status": "invalid",
        "ok": False,
        "algorithm": ALGORITHM,
        "key_id": None,
        "detail": (
            "signature matches no configured key — the checkpoint was altered "
            "or the signature was forged"
        ),
    }
