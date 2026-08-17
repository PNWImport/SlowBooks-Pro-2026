# ============================================================================
# Pay schedules — named pay calendars employees attach to.
# ----------------------------------------------------------------------------
# A bare PayFrequency enum says "biweekly" but not WHICH Fridays, when the
# submission cutoff falls, or what happens when a pay date lands on a
# weekend. A PaySchedule pins all three:
#
#   * frequency + anchor_pay_date  — the recurrence. The anchor is any known
#     real pay date; every other date is derived from it (weekly/biweekly
#     step in days; semi-monthly pays the anchor's day-of-month and that day
#     +15 capped to month end; monthly pays the anchor's day-of-month).
#   * submission_lead_days         — cutoff = pay date minus this many days.
#   * weekend_shift                — none / previous / next business day.
#
# Employees keep their pay_frequency column (it drives the withholding
# annualization) — attaching a schedule sets it as the source of truth and
# the employee routes keep the two in sync.
# ============================================================================

import enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Integer,
    String,
    func,
)

from app.database import Base
from app.models.payroll import PayFrequency


class WeekendShift(str, enum.Enum):
    NONE = "none"
    PREVIOUS_BUSINESS_DAY = "previous_business_day"
    NEXT_BUSINESS_DAY = "next_business_day"


class PaySchedule(Base):
    __tablename__ = "pay_schedules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    frequency = Column(Enum(PayFrequency), nullable=False)
    anchor_pay_date = Column(Date, nullable=False)
    submission_lead_days = Column(Integer, default=2)
    weekend_shift = Column(
        Enum(WeekendShift), default=WeekendShift.PREVIOUS_BUSINESS_DAY
    )
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
