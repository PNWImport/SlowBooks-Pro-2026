# ============================================================================
# E-signature — envelope creation, verification, admin views. Signing itself
# happens in the employee portal (routes/portal.py).
# ============================================================================

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.esign import EnvelopeKind, EnvelopeStatus, SignatureEnvelope
from app.models.payroll import Employee
from app.schemas.common import StrictModel

router = APIRouter(prefix="/api/esign", tags=["esign"])


def body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def signature_hash(content_hash: str, signer_name: str, timestamp_iso: str) -> str:
    """The sealed signature event: document + signer + moment, one hash."""
    material = f"{content_hash}|{signer_name}|{timestamp_iso}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class EnvelopeCreate(StrictModel):
    employee_id: int
    title: str
    body: str
    kind: str = "other"


def _response(e: SignatureEnvelope, include_body: bool = False) -> dict:
    out = {
        "id": e.id,
        "employee_id": e.employee_id,
        "employee_name": e.employee.full_name if e.employee else None,
        "kind": e.kind.value if e.kind else None,
        "title": e.title,
        "status": e.status.value if e.status else None,
        "content_hash": e.content_hash,
        "signer_name": e.signer_name,
        "signed_at": e.signed_at.isoformat() if e.signed_at else None,
        "signature_audit_id": e.signature_audit_id,
    }
    if include_body:
        out["body"] = e.body
    return out


@router.get("")
def list_envelopes(
    employee_id: int = Query(default=None),
    status: str = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(SignatureEnvelope).options(joinedload(SignatureEnvelope.employee))
    if employee_id is not None:
        q = q.filter(SignatureEnvelope.employee_id == employee_id)
    if status is not None:
        try:
            q = q.filter(SignatureEnvelope.status == EnvelopeStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status {status!r}")
    return [_response(e) for e in q.order_by(SignatureEnvelope.id.desc()).all()]


@router.get("/{envelope_id}")
def get_envelope(envelope_id: int, db: Session = Depends(get_db)):
    e = db.query(SignatureEnvelope).filter(SignatureEnvelope.id == envelope_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Envelope not found")
    return _response(e, include_body=True)


@router.post("", status_code=201)
def create_envelope(data: EnvelopeCreate, db: Session = Depends(get_db)):
    try:
        kind = EnvelopeKind(data.kind)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid kind {data.kind!r}")
    if not data.body.strip():
        raise HTTPException(status_code=400, detail="body must not be empty")
    if not db.query(Employee).filter(Employee.id == data.employee_id).first():
        raise HTTPException(status_code=404, detail="Employee not found")
    e = SignatureEnvelope(
        employee_id=data.employee_id,
        kind=kind,
        title=data.title,
        body=data.body,
        content_hash=body_hash(data.body),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return _response(e)


@router.post("/{envelope_id}/void")
def void_envelope(envelope_id: int, db: Session = Depends(get_db)):
    e = db.query(SignatureEnvelope).filter(SignatureEnvelope.id == envelope_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Envelope not found")
    if e.status == EnvelopeStatus.SIGNED:
        raise HTTPException(status_code=400, detail="Signed envelopes cannot be voided")
    e.status = EnvelopeStatus.VOIDED
    db.commit()
    return _response(e)


@router.get("/{envelope_id}/verify")
def verify_envelope(envelope_id: int, db: Session = Depends(get_db)):
    """Recompute both hashes and compare against the stored + audited values.

    body_intact: the stored body still hashes to the frozen content_hash.
    signature_intact: the audit row's hash still matches
    (content_hash, signer, signed_at) — so neither the document nor the
    signature event has been altered since sealing.
    """
    from app.models.document_audit import DocumentAudit

    e = db.query(SignatureEnvelope).filter(SignatureEnvelope.id == envelope_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Envelope not found")

    body_intact = body_hash(e.body) == e.content_hash
    signature_intact = None
    if e.status == EnvelopeStatus.SIGNED and e.signature_audit_id:
        audit = (
            db.query(DocumentAudit)
            .filter(DocumentAudit.id == e.signature_audit_id)
            .first()
        )
        if audit and e.signed_at:
            # SQLite hands back naive datetimes for values written tz-aware;
            # re-normalize to UTC so the recomputed isoformat matches what
            # was sealed.
            from datetime import timezone

            signed_at = e.signed_at
            if signed_at.tzinfo is None:
                signed_at = signed_at.replace(tzinfo=timezone.utc)
            expected = signature_hash(
                e.content_hash, e.signer_name or "", signed_at.isoformat()
            )
            signature_intact = audit.content_hash == expected
        else:
            signature_intact = False

    return {
        "envelope_id": e.id,
        "status": e.status.value if e.status else None,
        "body_intact": body_intact,
        "signature_intact": signature_intact,
        "verified": body_intact and (signature_intact in (True, None)),
    }
