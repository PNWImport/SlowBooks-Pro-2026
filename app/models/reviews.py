# ============================================================================
# Performance reviews — cycles of structured feedback with acknowledgment.
# ----------------------------------------------------------------------------
# One row per (employee, period): reviewer, rating, goals, feedback. The
# lifecycle is draft -> submitted (visible to the employee) -> acknowledged
# (employee has seen it, optionally with a comment). Deliberately simple —
# no calibration, no 360s — the record-keeping backbone reviews hang off.
# ============================================================================

import enum

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class ReviewStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"


class PerformanceReview(Base):
    __tablename__ = "performance_reviews"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(
        Integer, ForeignKey("employees.id"), nullable=False, index=True
    )
    reviewer_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(Enum(ReviewStatus), default=ReviewStatus.DRAFT)
    rating = Column(Integer, nullable=True)  # 1-5
    goals = Column(Text, nullable=True)
    feedback = Column(Text, nullable=True)
    employee_comment = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    employee = relationship("Employee", foreign_keys=[employee_id])
    reviewer = relationship("Employee", foreign_keys=[reviewer_id])
