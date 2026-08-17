# ============================================================================
# Document audit trail — a tamper-evident LINKED HASH CHAIN over every
# regulated document this app generates.
#
# Each row records a SHA-256 over one document's canonical content, and then
# links itself to the row before it:
#
#     chain_hash(N) = SHA256( prev_hash(N) | content_hash(N) |
#                             doc_type(N) | doc_key(N) | created_at(N) )
#     prev_hash(N)  = chain_hash(N-1)      (genesis: 64 zeros)
#
# The PDF footer prints the audit id + the first 16 hex chars of the CONTENT
# hash, so the original per-document workflow still holds:
#
#   1. Pull the matching `document_audits` row by id.
#   2. Re-render the document with the same inputs and recompute.
#   3. Compare — mismatch means the PDF does not match the data.
#
# What the linkage adds is the guarantee the per-document hash could not
# give. Because every row commits to its predecessor, removing a row,
# reordering rows, or splicing one in breaks every chain_hash downstream —
# `verify_chain()` reports the first break and its row id.
#
# LIMITS, stated plainly:
#   * The chain proves internal consistency. It cannot prove that the whole
#     tail was not truncated, because a shortened chain is still internally
#     valid. `AuditCheckpoint` closes that: it pins (tip id, tip hash, row
#     count) at a moment in time, so truncation past a checkpoint is
#     detectable. Checkpoints are only as good as their off-box copies —
#     an attacker with full DB write access can delete checkpoints too.
#   * Rows written before the chain existed were backfilled deterministically
#     by migration a2b3c4d5e6f9. That establishes a baseline going forward;
#     it is NOT retroactive proof that pre-backfill history was untampered.
#   * This is a hash chain, not a digital signature. The trust anchor is the
#     database plus whatever off-box checkpoint copies the operator keeps.
# ============================================================================

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base

# prev_hash of the first row in the chain.
GENESIS_HASH = "0" * 64


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentAudit(Base):
    __tablename__ = "document_audits"

    id = Column(Integer, primary_key=True)
    # Short tag identifying the document family: "w2", "w3", "940", "941",
    # "sui", "cobra", "esign", "new_hire", etc. Kept compact so it's easy to
    # filter on.
    doc_type = Column(String(20), nullable=False, index=True)
    # Free-form key uniquely identifying this issuance within its type — e.g.
    # "emp42-yr2026" for a W-2 or "yr2026-q3" for a 941. Indexed for lookup.
    doc_key = Column(String(80), nullable=False, index=True)
    # Full 64-char hex SHA-256 of the canonical content payload. This is what
    # the PDF footer prints and what a re-render reproduces.
    content_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, index=True)

    # --- chain linkage ---
    # chain_hash of the preceding row; GENESIS_HASH for the first.
    prev_hash = Column(String(64), nullable=True, index=True)
    # This row's own chain hash — the value the next row commits to.
    chain_hash = Column(String(64), nullable=True, index=True)


class AuditCheckpoint(Base):
    """A pinned tip of the chain, so tail truncation is detectable.

    Verification against a checkpoint answers "does the chain still contain
    everything it contained when this checkpoint was taken?" — which the
    chain alone cannot, since a truncated chain verifies fine on its own.

    Keep copies off the box (the operations runbook covers this): a
    checkpoint stored only in the same database an attacker can write is
    evidence, not proof.
    """

    __tablename__ = "audit_checkpoints"

    id = Column(Integer, primary_key=True)
    # The chain tip at checkpoint time.
    tip_audit_id = Column(Integer, nullable=False)
    tip_chain_hash = Column(String(64), nullable=False)
    # Row count at checkpoint time — a cheap independent truncation signal.
    row_count = Column(Integer, nullable=False)
    note = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, index=True)
