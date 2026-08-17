# ============================================================================
# Document audit endpoints — admin-only lookup of audit rows for verification.
#
# These power the "is this PDF authentic?" workflow:
#   1. Operator opens a tax-form PDF, reads "Audit ID #42" from the footer.
#   2. Operator hits GET /api/document-audits/42 to pull the canonical row.
#   3. Compares the hash printed in the PDF to the hash returned by the API.
#      Match -> the PDF data matches what was generated. Mismatch -> tamper
#      or version drift.
# ============================================================================

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.document_audit import AuditCheckpoint, DocumentAudit

router = APIRouter(prefix="/api/document-audits", tags=["document-audit"])


class DocumentAuditResponse(BaseModel):
    id: int
    doc_type: str
    doc_key: str
    content_hash: str
    created_at: Optional[datetime]
    prev_hash: Optional[str] = None
    chain_hash: Optional[str] = None
    model_config = {"from_attributes": True}


@router.get("", response_model=list[DocumentAuditResponse])
def list_audits(
    doc_type: Optional[str] = Query(default=None),
    doc_key: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List recent document audit rows, newest first. Optional filters
    narrow by doc family (`w2`, `941`, ...) or by the type-specific key."""
    q = db.query(DocumentAudit)
    if doc_type:
        q = q.filter(DocumentAudit.doc_type == doc_type)
    if doc_key:
        q = q.filter(DocumentAudit.doc_key == doc_key)
    return q.order_by(DocumentAudit.id.desc()).limit(limit).all()


@router.get("/{audit_id}", response_model=DocumentAuditResponse)
def get_audit(audit_id: int, db: Session = Depends(get_db)):
    """Look up one audit row by its ID — the ID printed in the PDF footer."""
    row = db.query(DocumentAudit).filter(DocumentAudit.id == audit_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Audit row not found")
    return row


@router.get("/verify/{content_hash}", response_model=list[DocumentAuditResponse])
def verify_hash(content_hash: str, db: Session = Depends(get_db)):
    """Find every audit row matching this full SHA-256 hash. Used when an
    auditor has the PDF's hash but not the ID — e.g. they recomputed it
    independently and want to confirm it's known to the system."""
    if len(content_hash) != 64 or not all(
        c in "0123456789abcdef" for c in content_hash
    ):
        raise HTTPException(status_code=400, detail="content_hash must be 64 hex chars")
    return (
        db.query(DocumentAudit)
        .filter(DocumentAudit.content_hash == content_hash)
        .order_by(DocumentAudit.id.desc())
        .all()
    )


# --- chain verification -----------------------------------------------------
#
# The per-row endpoints above answer "does this PDF match its data?". These
# answer the stronger question the § 164.312(c)(1) integrity claim rests on:
# "has anything been removed from or reordered inside the audit trail?"


class CheckpointRequest(BaseModel):
    note: Optional[str] = None


@router.get("/chain/verify")
def verify_audit_chain(
    limit: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    """Walk the hash chain and report the first break, if any.

    Returns a report (never raises on a broken chain) — an auditor needs to
    see WHERE it broke, not just that it did.
    """
    from app.services.document_audit import verify_chain

    return verify_chain(db, limit=limit)


@router.get("/chain/checkpoints")
def list_checkpoints(
    limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)
):
    rows = (
        db.query(AuditCheckpoint).order_by(AuditCheckpoint.id.desc()).limit(limit).all()
    )
    return [
        {
            "id": c.id,
            "tip_audit_id": c.tip_audit_id,
            "tip_chain_hash": c.tip_chain_hash,
            "row_count": c.row_count,
            "note": c.note,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in rows
    ]


@router.post("/chain/checkpoints", status_code=201)
def create_audit_checkpoint(data: CheckpointRequest, db: Session = Depends(get_db)):
    """Pin the current chain tip so later tail-truncation is detectable.

    Refuses on a broken chain — checkpointing known-bad state would launder
    the break into the baseline. Keep copies off the box.
    """
    from app.services.document_audit import create_checkpoint

    try:
        checkpoint = create_checkpoint(db, note=data.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "id": checkpoint.id,
        "tip_audit_id": checkpoint.tip_audit_id,
        "tip_chain_hash": checkpoint.tip_chain_hash,
        "row_count": checkpoint.row_count,
        "created_at": checkpoint.created_at.isoformat(),
    }


@router.get("/chain/checkpoints/{checkpoint_id}/verify")
def verify_checkpoint(checkpoint_id: int, db: Session = Depends(get_db)):
    """Prove the chain still contains everything it did at checkpoint time."""
    from app.services.document_audit import verify_against_checkpoint

    checkpoint = (
        db.query(AuditCheckpoint).filter(AuditCheckpoint.id == checkpoint_id).first()
    )
    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return verify_against_checkpoint(db, checkpoint)
