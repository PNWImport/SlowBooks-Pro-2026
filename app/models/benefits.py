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
# What is deliberately NOT encrypted, and why: plan name and kind, coverage
# dates, premium amounts, and the employee_id foreign key. Those are queried,
# sorted and joined on — the ACA month-of-coverage derivation filters on plan
# kind and coverage windows — and Fernet output is randomized, so encrypting
# them would break the queries without hiding much (an attacker with table
# access already knows which employees have medical coverage from the
# enrollment rows themselves). Encrypting those needs a blind-index design,
# tracked in docs/todo.md.
# ============================================================================

import enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
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
from app.services.encryption import EncryptedDate, EncryptedString


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
    kind = Column(Enum(BenefitKind), default=BenefitKind.MEDICAL)
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
    coverage_start = Column(Date, nullable=False)
    coverage_end = Column(Date, nullable=True)  # null = ongoing
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
