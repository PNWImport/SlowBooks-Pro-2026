# ============================================================================
# Benefits — plans, enrollments, dependents. Records only, no carrier feeds.
# ----------------------------------------------------------------------------
# The record-keeping half of benefits administration: which plans exist,
# who is enrolled with which dependents, and over what coverage months.
# That is exactly the data ACA reporting (1095-B/C + 1094) and COBRA
# election notices need, and both generate locally from these tables.
# Carrier enrollment feeds (EDI 834) are external integrations and out of
# scope by design.
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
    carrier_name = Column(String(120), nullable=True)
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
    name = Column(String(200), nullable=False)
    relationship_kind = Column(String(30), nullable=True)  # spouse, child, ...
    ssn_last_four = Column(String(4), nullable=True)
    dob = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    enrollment = relationship("BenefitEnrollment", back_populates="dependents")
