# ============================================================================
# Document audit hashing — canonical SHA-256 over a document payload, plus the
# append-and-link machinery that makes `document_audits` a real hash chain.
#
# Checkpoints live here too, including their signing and off-box export. The
# CLI at the bottom is the piece an operator actually schedules:
#
#   python -m app.services.document_audit checkpoint --note "Q3 close" \
#       --export /mnt/worm/slowbooks/2026-q3.json
#   python -m app.services.document_audit verify-artifact /mnt/worm/.../file.json
#
# See app/services/audit_signing.py for what a signature does and does not
# prove.
# ============================================================================

import hashlib
import json
import logging
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
from app.services import audit_signing

logger = logging.getLogger(__name__)


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

    Signs the pinned tuple when a signing key is configured, so the row
    cannot be forged by database write access. Unconfigured means unsigned,
    not an error — the checkpoint still works, it just carries less weight,
    and every verification says so.
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
    signed = audit_signing.sign(checkpoint_payload(checkpoint))
    if signed:
        checkpoint.signature = signed["signature"]
        checkpoint.signature_key_id = signed["signature_key_id"]
        checkpoint.signature_algorithm = signed["signature_algorithm"]

    db.add(checkpoint)
    db.commit()
    db.refresh(checkpoint)
    return checkpoint


# --- signing, export, and off-box verification ------------------------------


def checkpoint_payload(checkpoint: AuditCheckpoint) -> dict:
    """The exact tuple a checkpoint's signature commits to."""
    return audit_signing.build_payload(
        tip_audit_id=checkpoint.tip_audit_id,
        tip_chain_hash=checkpoint.tip_chain_hash,
        row_count=checkpoint.row_count,
        created_at=checkpoint.created_at,
        note=checkpoint.note,
    )


def verify_checkpoint_signature(checkpoint: AuditCheckpoint) -> dict:
    """Verify the stored signature over the stored tuple.

    Because the payload is rebuilt from the row's own columns, editing any of
    them — including the note, or back-dating created_at — turns a `valid`
    into an `invalid`.
    """
    return audit_signing.verify(checkpoint_payload(checkpoint), checkpoint.signature)


def export_checkpoint(checkpoint: AuditCheckpoint) -> dict:
    """A self-contained signed artifact to copy off the box.

    THIS is what closes the "delete the rows and the checkpoints too" hole.
    The artifact carries the signed payload, so it can be fed back through
    `verify_artifact()` later and prove what the chain contained — with no
    checkpoint row left in the database at all. Write it to WORM storage or a
    second system; the operations runbook has the cron.

    `checkpoint_id` and `exported_at` sit OUTSIDE `payload` and are therefore
    NOT signed: they are provenance notes for a human, not claims. Everything
    load-bearing is inside `payload`.
    """
    signature_state = verify_checkpoint_signature(checkpoint)
    return {
        "artifact": "slowbooks-audit-checkpoint",
        "artifact_version": 1,
        "payload": checkpoint_payload(checkpoint),
        "signature": checkpoint.signature,
        "signature_key_id": checkpoint.signature_key_id,
        "signature_algorithm": checkpoint.signature_algorithm
        or (audit_signing.ALGORITHM if checkpoint.signature else None),
        "signature_status_at_export": signature_state["status"],
        # Unsigned provenance — informational only.
        "checkpoint_id": checkpoint.id,
        "exported_at": _iso(datetime.now(timezone.utc)),
        "how_to_verify": (
            "signature = HMAC-SHA256(key, "
            'json.dumps(payload, sort_keys=True, separators=(",", ":")))  '
            "— or POST this whole document to "
            "/api/document-audits/chain/checkpoints/verify-artifact"
        ),
    }


def _compare_to_chain(
    db: Session, tip_audit_id: int, tip_chain_hash: str, row_count: int
) -> tuple[list[str], int]:
    """Does the live chain still contain what a pinned tuple attests to?

    Three ways this fails, and all three are worth distinguishing:
      * the pinned tip row is gone         -> the tail was truncated
      * the pinned tip's hash changed      -> that row was altered
      * fewer rows than at checkpoint time -> rows were removed somewhere
    """
    problems: list[str] = []
    tip = db.query(DocumentAudit).filter(DocumentAudit.id == tip_audit_id).first()
    if tip is None:
        problems.append(
            f"checkpointed tip audit id {tip_audit_id} no longer exists — "
            "the chain was truncated"
        )
    elif tip.chain_hash != tip_chain_hash:
        problems.append(
            f"audit id {tip_audit_id} no longer has its checkpointed "
            "chain_hash — that row was altered"
        )

    current_count = db.query(func.count(DocumentAudit.id)).scalar() or 0
    if current_count < row_count:
        problems.append(
            f"row count fell from {row_count} to {current_count} — "
            f"{row_count - current_count} row(s) removed"
        )
    return problems, current_count


def verify_against_checkpoint(db: Session, checkpoint: AuditCheckpoint) -> dict:
    """Prove the chain still contains what it did at checkpoint time.

    `ok` requires three things together: the chain verifies internally, it
    still holds the checkpointed tip and row count, and the checkpoint's own
    signature checks out. An unsigned checkpoint therefore reports ok=False
    with `signature.status == "unsigned"` — the containment finding is still
    in `problems` (empty if containment held), so an operator can see the
    difference between "the chain was truncated" and "this checkpoint was
    never signed".
    """
    problems, current_count = _compare_to_chain(
        db, checkpoint.tip_audit_id, checkpoint.tip_chain_hash, checkpoint.row_count
    )
    chain = verify_chain(db)
    signature = verify_checkpoint_signature(checkpoint)
    return {
        "ok": not problems and chain["ok"] and signature["ok"],
        "contains_checkpointed_state": not problems and chain["ok"],
        "checkpoint_id": checkpoint.id,
        "checkpoint_created_at": _iso(checkpoint.created_at),
        "checkpoint_row_count": checkpoint.row_count,
        "current_row_count": current_count,
        "problems": problems,
        "signature": signature,
        "chain": chain,
    }


def verify_artifact(db: Session, artifact: dict) -> dict:
    """Verify an off-box checkpoint artifact against the live chain.

    The off-box workflow, end to end: export an artifact, keep it somewhere
    the application cannot reach, then bring it back and run this. It needs no
    checkpoint row — `checkpoint_row_present` reports whether the database
    still has its copy, so "someone deleted the checkpoints" shows up as a
    distinct finding rather than as a silent pass.

    A malformed artifact raises ValueError; a valid artifact over a tampered
    chain returns ok=False with the reason.
    """
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be a JSON object")
    payload = artifact.get("payload")
    problems_in_shape = audit_signing.payload_problems(payload)
    if problems_in_shape:
        raise ValueError("; ".join(problems_in_shape))

    signature = audit_signing.verify(payload, artifact.get("signature"))
    problems, current_count = _compare_to_chain(
        db,
        int(payload["tip_audit_id"]),
        str(payload["tip_chain_hash"]),
        int(payload["row_count"]),
    )
    chain = verify_chain(db)

    # Is the database's own copy still there? Matched on the signed tuple, not
    # on the artifact's unsigned checkpoint_id, so a renumbered row still
    # counts as present.
    row_present = (
        db.query(func.count(AuditCheckpoint.id))
        .filter(
            AuditCheckpoint.tip_audit_id == int(payload["tip_audit_id"]),
            AuditCheckpoint.tip_chain_hash == str(payload["tip_chain_hash"]),
        )
        .scalar()
        or 0
    ) > 0
    if not row_present:
        problems.append(
            "the database no longer holds a checkpoint for this pinned tip — "
            "the checkpoint row was deleted, and only this off-box artifact "
            "still attests to that state"
        )

    return {
        "ok": not problems and chain["ok"] and signature["ok"],
        "contains_checkpointed_state": not problems and chain["ok"],
        "checkpoint_row_present": row_present,
        "artifact_checkpoint_id": artifact.get("checkpoint_id"),
        "checkpoint_created_at": payload.get("created_at"),
        "checkpoint_row_count": int(payload["row_count"]),
        "current_row_count": current_count,
        "note": payload.get("note") or "",
        "problems": problems,
        "signature": signature,
        "chain": chain,
    }


def resign_checkpoints(db: Session) -> dict:
    """Re-sign checkpoints that verify only under the rotated-out key.

    Deliberately refuses to sign checkpoints that were never signed. Signing
    one now would assert that the current key attested to that tuple at that
    time, which is exactly the thing nobody can know — an attacker who created
    a bogus unsigned checkpoint would get it laundered into a signed one.
    Those are counted under `left_unsigned` and stay unsigned forever; take a
    fresh checkpoint instead.
    """
    summary = {
        "checked": 0,
        "resigned": 0,
        "already_current": 0,
        "left_unsigned": 0,
        "invalid": 0,
    }
    if not audit_signing.signing_configured():
        summary["error"] = (
            "AUDIT_CHECKPOINT_SIGNING_SECRET is not configured — nothing to "
            "re-sign under"
        )
        return summary

    for checkpoint in db.query(AuditCheckpoint).order_by(AuditCheckpoint.id).all():
        summary["checked"] += 1
        state = verify_checkpoint_signature(checkpoint)
        if state["status"] == "unsigned":
            summary["left_unsigned"] += 1
            continue
        if state["status"] == "valid":
            summary["already_current"] += 1
            continue
        if state["status"] != "valid_previous_key":
            summary["invalid"] += 1
            logger.error(
                "resign: checkpoint #%s signature is %s — left alone",
                checkpoint.id,
                state["status"],
            )
            continue
        signed = audit_signing.sign(checkpoint_payload(checkpoint))
        checkpoint.signature = signed["signature"]
        checkpoint.signature_key_id = signed["signature_key_id"]
        checkpoint.signature_algorithm = signed["signature_algorithm"]
        summary["resigned"] += 1

    if summary["resigned"]:
        db.commit()
    return summary


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


# --- operator CLI -----------------------------------------------------------


def _cli() -> None:
    """`python -m app.services.document_audit <cmd>` — the off-box workflow.

    Exists because "keep a copy off the box" has to be something a cron job
    can do. Exits non-zero on any verification failure so a scheduler notices.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m app.services.document_audit")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("verify", help="Walk the chain and report any break")

    checkpoint = sub.add_parser(
        "checkpoint", help="Pin the current chain tip and sign it"
    )
    checkpoint.add_argument(
        "--note", default=None, help="Label stored in the signature"
    )
    checkpoint.add_argument(
        "--export",
        metavar="PATH",
        default=None,
        help="Also write the signed artifact here (use a WORM mount)",
    )

    export = sub.add_parser("export", help="Write an existing checkpoint's artifact")
    export.add_argument("checkpoint_id", type=int)
    export.add_argument("--out", metavar="PATH", default=None, help="Default: stdout")

    artifact = sub.add_parser(
        "verify-artifact", help="Verify an off-box artifact against the live chain"
    )
    artifact.add_argument("path", help="Artifact JSON written by export/checkpoint")

    sub.add_parser("resign", help="Re-sign checkpoints left on the previous key")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(2)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if args.cmd == "verify":
            report = verify_chain(db)
            print(json.dumps(report, indent=2, default=str))
            sys.exit(0 if report["ok"] else 1)

        if args.cmd == "checkpoint":
            try:
                row = create_checkpoint(db, note=args.note)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                sys.exit(1)
            doc = export_checkpoint(row)
            if args.export:
                with open(args.export, "w", encoding="utf-8") as handle:
                    json.dump(doc, handle, indent=2)
                print(f"checkpoint #{row.id} written to {args.export}")
            else:
                print(json.dumps(doc, indent=2))
            if not row.signature:
                print(
                    "warning: checkpoint is UNSIGNED — set "
                    "AUDIT_CHECKPOINT_SIGNING_SECRET",
                    file=sys.stderr,
                )
                sys.exit(1)
            sys.exit(0)

        if args.cmd == "export":
            row = (
                db.query(AuditCheckpoint)
                .filter(AuditCheckpoint.id == args.checkpoint_id)
                .first()
            )
            if row is None:
                print(f"error: no checkpoint #{args.checkpoint_id}", file=sys.stderr)
                sys.exit(1)
            doc = export_checkpoint(row)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as handle:
                    json.dump(doc, handle, indent=2)
                print(f"checkpoint #{row.id} written to {args.out}")
            else:
                print(json.dumps(doc, indent=2))
            sys.exit(0)

        if args.cmd == "verify-artifact":
            with open(args.path, encoding="utf-8") as handle:
                doc = json.load(handle)
            try:
                result = verify_artifact(db, doc)
            except ValueError as exc:
                print(f"error: malformed artifact: {exc}", file=sys.stderr)
                sys.exit(2)
            print(json.dumps(result, indent=2, default=str))
            sys.exit(0 if result["ok"] else 1)

        if args.cmd == "resign":
            summary = resign_checkpoints(db)
            print(json.dumps(summary, indent=2))
            sys.exit(1 if summary.get("error") or summary["invalid"] else 0)
    finally:
        db.close()


if __name__ == "__main__":
    _cli()
