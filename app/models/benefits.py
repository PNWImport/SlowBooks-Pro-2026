# ============================================================================
# Benefits — plans, enrollments, dependents. Records only, no carrier feeds.
# ----------------------------------------------------------------------------
# The record-keeping half of benefits administration: which plans exist,
# who is enrolled with which dependents, and over what coverage months.
# That is exactly the data ACA reporting (1095-B/C + 1094) and COBRA
# election notices need, and both generate locally from these tables.
# Carrier enrollment feeds (EDI 834) are external integrations and out of
# scope by design.
#
# ePHI TREATMENT. Health-plan enrollment tied to a named individual is
# individually identifiable information relating to payment for healthcare,
# so the identifying fields are Fernet-encrypted at rest with the same
# scheme and key as employee bank PII: the carrier name, and every dependent
# identifier (name, SSN last-4, date of birth — a DOB is an identifier under
# HIPAA's safe-harbor list). EncryptedString/EncryptedDate make this
# transparent, so call sites still read and write plaintext.
#
# The enrollment metadata that made the coverage itself readable is encrypted
# too: the plan KIND (so "this is a medical plan" is not sitting in plaintext)
# and the COVERAGE WINDOW dates. Those were the two halves of "which employees
# hold medical coverage over which months", which is the finding that mattered
# more than the dependents' names.
#
# Each needed a different mechanism, because encryption breaks queries:
#
#   * `kind` is filtered in SQL by the ACA derivation, so it carries a blind
#     index (`kind_bidx`) — a keyed deterministic hash the application can
#     compute and a reader of the table cannot. Equality queries still work.
#     What that concedes: bucket sizes are visible, so an attacker who knows
#     this is an HR system will guess the biggest bucket is MEDICAL. It still
#     costs them DENTAL vs VISION vs LIFE, which they could previously read.
#   * `coverage_start` / `coverage_end` need no index at all. The only SQL
#     predicate on them is `coverage_end IS NULL` (the open-enrollment check),
#     and NULL survives encryption. Every other comparison — the ACA
#     month-of-coverage rule — happens in Python on decrypted values. A blind
#     index would not have helped anyway: it answers equality, and those are
#     range comparisons.
#
# What is deliberately NOT encrypted, and why:
#
#   * plan name, premium amounts, `provides_mec`, `relationship_kind`,
#     enrollment `status` — plan properties and categories, not identifiers.
#     `provides_mec` is a boolean: a blind index over two values is a
#     two-bucket histogram, i.e. plaintext with extra steps.
#   * `employee_id`. This is the deliberate stopping point, not an oversight.
#     Encrypting a foreign key means giving up the FK constraint, the ON
#     DELETE CASCADE, and the ORM relationship — the database could no longer
#     guarantee an enrollment points at a real employee, and orphan rows
#     become possible. In exchange, a blind index would still group every
#     enrollment belonging to one person by construction, so the fact that
#     *somebody* holds coverage across these rows stays visible either way.
#     Trading referential integrity for that is a bad trade; concealing it
#     properly needs per-row key derivation, which is a different design.
#     docs/hipaa-compliance.md § 4 records this as the residual gap.
# ============================================================================

import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.services.blind_index import blind_index, register_blind_index
from app.services.encryption import EncryptedDate, EncryptedEnum, EncryptedString


class BenefitKind(str, enum.Enum):
    MEDICAL = "medical"
    DENTAL = "dental"
    VISION = "vision"
    LIFE = "life"
    DISABILITY = "disability"
    OTHER = "other"


class EnrollmentStatus(str, enum.Enum):
    ACTIVE = "active"
    TERMINATED = "terminated"
    COBRA = "cobra"


class BenefitPlan(Base):
    __tablename__ = "benefit_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True)
    # Encrypted at rest, with a blind index because the ACA derivation filters
    # on it in SQL. Query it through `plan_kind_index()` below, never by
    # comparing `kind` in a WHERE clause — that compares ciphertext.
    kind = Column(EncryptedEnum(BenefitKind, 255), default=BenefitKind.MEDICAL)
    kind_bidx = Column(String(64), nullable=True, index=True)
    # Encrypted at rest (borderline PHI: implies a health context).
    carrier_name = Column(EncryptedString(500), nullable=True)
    # Self-insured medical plans report covered individuals on 1095 Part III
    # (employer files as coverage provider); fully-insured plans leave that
    # to the carrier's 1095-B.
    self_insured = Column(Boolean, default=False)
    # Minimum essential coverage — drives ACA months-of-coverage reporting.
    provides_mec = Column(Boolean, default=True)
    monthly_premium_employee = Column(Numeric(12, 2), default=0)
    monthly_premium_employer = Column(Numeric(12, 2), default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    enrollments = relationship("BenefitEnrollment", back_populates="plan")


class BenefitEnrollment(Base):
    __tablename__ = "benefit_enrollments"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(
        Integer, ForeignKey("employees.id"), nullable=False, index=True
    )
    plan_id = Column(Integer, ForeignKey("benefit_plans.id"), nullable=False)
    # The coverage window is encrypted. No blind index: the only SQL predicate
    # is `coverage_end IS NULL`, and NULL survives encryption. The ACA
    # month-of-coverage rule compares these in Python — and those are range
    # comparisons, which a blind index cannot answer anyway.
    coverage_start = Column(EncryptedDate(255), nullable=False)
    coverage_end = Column(EncryptedDate(255), nullable=True)  # null = ongoing
    status = Column(Enum(EnrollmentStatus), default=EnrollmentStatus.ACTIVE)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    employee = relationship("Employee")
    plan = relationship("BenefitPlan", back_populates="enrollments")
    dependents = relationship(
        "BenefitDependent", back_populates="enrollment", cascade="all, delete-orphan"
    )


class BenefitDependent(Base):
    __tablename__ = "benefit_dependents"

    id = Column(Integer, primary_key=True, index=True)
    enrollment_id = Column(
        Integer,
        ForeignKey("benefit_enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Dependent identifiers — encrypted at rest. These are family members
    # who are not employees and never consented to this system directly.
    name = Column(EncryptedString(500), nullable=False)
    # Relationship stays plaintext: "spouse"/"child" is a category, not an
    # identifier, and the 1095 covered-individuals listing groups on it.
    relationship_kind = Column(String(30), nullable=True)
    ssn_last_four = Column(EncryptedString(255), nullable=True)
    dob = Column(EncryptedDate(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    enrollment = relationship("BenefitEnrollment", back_populates="dependents")


# --- blind-index wiring ------------------------------------------------------
#
# Registered on the mapper rather than set at call sites. A blind index that
# one code path forgets to write is worse than no index: the row silently
# stops matching the query that filters on it, and nothing raises.

_KIND_DOMAIN = "benefit_plans.kind"

register_blind_index(BenefitPlan, "kind", "kind_bidx", _KIND_DOMAIN)


def plan_kind_index(kind: BenefitKind) -> str:
    """The value to compare `BenefitPlan.kind_bidx` against in a query.

        db.query(BenefitPlan).filter(
            BenefitPlan.kind_bidx == plan_kind_index(BenefitKind.MEDICAL)
        )

    Exists so no caller has to know the domain string, and so a filter on the
    encrypted `kind` column — which would compare ciphertext and match nothing
    — is the obviously-wrong-looking option.
    """
    return blind_index(_KIND_DOMAIN, kind)
