# ============================================================================
# E-signature envelopes — signing sealed into the document-audit ledger.
# ----------------------------------------------------------------------------
# An envelope freezes a document body (offer letter, I-9 acknowledgment,
# handbook receipt) with its SHA-256 at creation. The employee signs in the
# self-service portal by typing their name; the signature event hashes
# (document hash + signer + UTC timestamp) into the same document_audits
# LEDGER the tax forms use, so the pair (envelope, audit row) records what
# was signed, by whom, and when — and any later edit to the stored body is
# detectable because it no longer matches the frozen hash.
#
# Ledger, not chain: rows are independent, so a deleted audit row leaves no
# trace behind. What this DOES prove is that a signed body was not altered.
# See docs/hipaa-compliance.md § 164.312(c)(1).
#
# ESIGN/UETA hinge on intent, consent, association, and retention. Typed
# signatures satisfy them when those elements are captured; this model
# captures them. It is still a generic implementation — run it past
# counsel before relying on it for I-9s specifically, which carry their
# own federal e-signature requirements.
# ============================================================================

import enum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class EnvelopeKind(str, enum.Enum):
    OFFER_LETTER = "offer_letter"
    I9_ACKNOWLEDGMENT = "i9_acknowledgment"
    HANDBOOK = "handbook"
    POLICY = "policy"
    OTHER = "other"


class EnvelopeStatus(str, enum.Enum):
    PENDING = "pending"
    SIGNED = "signed"
    DECLINED = "declined"
    VOIDED = "voided"


class SignatureEnvelope(Base):
    __tablename__ = "signature_envelopes"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(
        Integer, ForeignKey("employees.id"), nullable=False, index=True
    )
    kind = Column(Enum(EnvelopeKind), default=EnvelopeKind.OTHER)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)  # the document text, frozen at creation
    content_hash = Column(String(64), nullable=False)  # SHA-256 of body at creation

    status = Column(Enum(EnvelopeStatus), default=EnvelopeStatus.PENDING)
    signer_name = Column(String(200), nullable=True)  # typed signature
    signed_at = Column(DateTime(timezone=True), nullable=True)
    # The sealed audit row: hash of (content_hash, signer, timestamp).
    signature_audit_id = Column(
        Integer, ForeignKey("document_audits.id"), nullable=True
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    employee = relationship("Employee")
