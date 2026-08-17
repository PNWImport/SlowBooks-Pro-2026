# ============================================================================
# Document audit hashing — canonical SHA-256 over a document payload, plus the
# append-and-link machinery that makes `document_audits` a real hash chain.
# ============================================================================

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document_audit import (
    GENESIS_HASH,
    AuditCheckpoint,
    DocumentAudit,
)


def _canonical(value: Any) -> Any:
    """Reshape a payload so json.dumps gives a stable byte string. Decimals
    serialize as strings (no float rounding); dates/datetimes as ISO-8601.

    Note: `datetime` is a subclass of `date`, so the `date` branch catches
    both. Ordering matters — Decimal first because Decimal isn't a Number
    subclass json.dumps recognizes.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def compute_doc_hash(payload: dict) -> str:
    """SHA-256 over a sorted, canonical JSON serialization of `payload`.

    The hash is content-only — no timestamps, no audit IDs — so re-rendering
    the same data on a different day yields the same hash. The audit row is
    where time-of-issue lives.
    """
    canonical = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- chain linkage ----------------------------------------------------------


def _iso(value) -> str:
    """Stable timestamp rendering for the chain hash.

    SQLite hands back naive datetimes for values written tz-aware, so
    normalize to UTC before formatting — otherwise a row's chain hash would
    not reproduce after a round-trip through the database.
    """
    if value is None:
        return ""
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def compute_chain_hash(
    prev_hash: str, content_hash: str, doc_type: str, doc_key: str, created_at
) -> str:
    """The link. Commits to the predecessor AND to this row's own identity.

    Including doc_type/doc_key/created_at means an attacker cannot relabel or
    re-date a row while keeping its content hash and linkage intact.
    """
    material = "|".join(
        [
            prev_hash or GENESIS_HASH,
            content_hash or "",
            doc_type or "",
            doc_key or "",
            _iso(created_at),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _chain_tip(db: Session, lock: bool = False):
    """The current last row of the chain, optionally row-locked.

    Appending needs serialization: two concurrent writers that both read the
    same tip would each link to it and fork the chain. On PostgreSQL the
    SELECT ... FOR UPDATE makes the second writer wait. SQLite serializes
    writers already, and does not support FOR UPDATE, so the lock is skipped
    there.
    """
    query = db.query(DocumentAudit).order_by(DocumentAudit.id.desc())
    if lock and db.bind is not None and db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    return query.first()


def record_doc_audit(
    db: Session, doc_type: str, doc_key: str, content_hash: str
) -> DocumentAudit:
    """Append one DocumentAudit row, linked to the current chain tip.

    The caller passes the same content hash into the PDF footer so the row and
    the printed page are bound together by id + hash.
    """
    tip = _chain_tip(db, lock=True)
    prev_hash = (tip.chain_hash if tip and tip.chain_hash else None) or GENESIS_HASH

    created_at = datetime.now(timezone.utc)
    audit = DocumentAudit(
        doc_type=doc_type,
        doc_key=doc_key,
        content_hash=content_hash,
        created_at=created_at,
        prev_hash=prev_hash,
    )
    audit.chain_hash = compute_chain_hash(
        prev_hash, content_hash, doc_type, doc_key, created_at
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def audit_footer_context(audit: DocumentAudit) -> dict:
    """Shape the audit dict the way the PDF templates expect."""
    return {
        "id": audit.id,
        "hash": audit.content_hash,
        "hash_short": audit.content_hash[:16],
        "chain_hash": audit.chain_hash,
        "timestamp": (
            audit.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            if audit.created_at
            else ""
        ),
    }


# --- verification -----------------------------------------------------------


def verify_chain(db: Session, limit: int | None = None) -> dict:
    """Walk the chain in id order and recompute every link.

    Returns a report rather than raising: an auditor wants the whole picture,
    including WHERE the first break is. `ok` is True only when every row's
    prev_hash matches its predecessor's chain_hash and every chain_hash
    recomputes from the row's own fields.

    Rows with no chain_hash (written before the chain existed and never
    backfilled) are counted as `unchained` and do not fail verification —
    they are reported so the gap is visible.
    """
    query = db.query(DocumentAudit).order_by(DocumentAudit.id)
    if limit:
        query = query.limit(limit)
    rows = query.all()

    breaks: list[dict] = []
    unchained = 0
    expected_prev = GENESIS_HASH
    verified = 0

    for row in rows:
        if not row.chain_hash:
            unchained += 1
            continue

        if row.prev_hash != expected_prev:
            breaks.append(
                {
                    "audit_id": row.id,
                    "reason": "prev_hash does not match the preceding row's "
                    "chain_hash — a row was deleted, reordered, or inserted",
                    "expected_prev_hash": expected_prev,
                    "found_prev_hash": row.prev_hash,
                }
            )

        recomputed = compute_chain_hash(
            row.prev_hash, row.content_hash, row.doc_type, row.doc_key, row.created_at
        )
        if recomputed != row.chain_hash:
            breaks.append(
                {
                    "audit_id": row.id,
                    "reason": "chain_hash does not recompute from this row's "
                    "fields — content_hash, doc_type, doc_key or created_at "
                    "was altered",
                    "expected_chain_hash": recomputed,
                    "found_chain_hash": row.chain_hash,
                }
            )

        expected_prev = row.chain_hash
        verified += 1

    tip = rows[-1] if rows else None
    return {
        "ok": not breaks,
        "rows_total": len(rows),
        "rows_verified": verified,
        "rows_unchained": unchained,
        "breaks": breaks,
        "tip_audit_id": tip.id if tip else None,
        "tip_chain_hash": tip.chain_hash if tip else None,
        "note": (
            "A chain that verifies proves no row was altered, removed, or "
            "reordered WITHIN it. It cannot detect truncation of the tail — "
            "compare against a checkpoint for that."
        ),
    }


def create_checkpoint(db: Session, note: str | None = None) -> AuditCheckpoint:
    """Pin the current chain tip so later truncation is detectable.

    Refuses to checkpoint a broken chain: a checkpoint over known-bad state
    would launder the break into the baseline.
    """
    report = verify_chain(db)
    if not report["ok"]:
        raise ValueError(
            "refusing to checkpoint a broken chain — "
            f"{len(report['breaks'])} break(s), first at audit id "
            f"{report['breaks'][0]['audit_id']}"
        )
    if report["tip_audit_id"] is None:
        raise ValueError("nothing to checkpoint — the audit chain is empty")

    checkpoint = AuditCheckpoint(
        tip_audit_id=report["tip_audit_id"],
        tip_chain_hash=report["tip_chain_hash"],
        row_count=db.query(func.count(DocumentAudit.id)).scalar() or 0,
        note=note,
        created_at=datetime.now(timezone.utc),
    )
    db.add(checkpoint)
    db.commit()
    db.refresh(checkpoint)
    return checkpoint


def verify_against_checkpoint(db: Session, checkpoint: AuditCheckpoint) -> dict:
    """Prove the chain still contains what it did at checkpoint time.

    Three ways this fails, and all three are worth distinguishing:
      * the pinned tip row is gone         -> the tail was truncated
      * the pinned tip's hash changed      -> that row was altered
      * fewer rows than at checkpoint time -> rows were removed somewhere
    """
    problems: list[str] = []
    tip = (
        db.query(DocumentAudit)
        .filter(DocumentAudit.id == checkpoint.tip_audit_id)
        .first()
    )
    if tip is None:
        problems.append(
            f"checkpointed tip audit id {checkpoint.tip_audit_id} no longer "
            "exists — the chain was truncated"
        )
    elif tip.chain_hash != checkpoint.tip_chain_hash:
        problems.append(
            f"audit id {checkpoint.tip_audit_id} no longer has its "
            "checkpointed chain_hash — that row was altered"
        )

    current_count = db.query(func.count(DocumentAudit.id)).scalar() or 0
    if current_count < checkpoint.row_count:
        problems.append(
            f"row count fell from {checkpoint.row_count} to {current_count} — "
            f"{checkpoint.row_count - current_count} row(s) removed"
        )

    chain = verify_chain(db)
    return {
        "ok": not problems and chain["ok"],
        "checkpoint_id": checkpoint.id,
        "checkpoint_created_at": _iso(checkpoint.created_at),
        "checkpoint_row_count": checkpoint.row_count,
        "current_row_count": current_count,
        "problems": problems,
        "chain": chain,
    }


def backfill_chain(db: Session) -> int:
    """Link any rows that have no chain_hash, in id order.

    Used by migration a2b3c4d5e6f9 and safe to re-run: rows that already have
    a chain_hash are left alone, so this only ever closes gaps. Establishes a
    baseline going forward — it is not retroactive proof about pre-backfill
    history.
    """
    rows = db.query(DocumentAudit).order_by(DocumentAudit.id).all()
    linked = 0
    prev_hash = GENESIS_HASH
    for row in rows:
        if row.chain_hash:
            prev_hash = row.chain_hash
            continue
        row.prev_hash = prev_hash
        row.chain_hash = compute_chain_hash(
            prev_hash, row.content_hash, row.doc_type, row.doc_key, row.created_at
        )
        prev_hash = row.chain_hash
        linked += 1
    if linked:
        db.commit()
    return linked
