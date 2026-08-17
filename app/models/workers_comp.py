# ============================================================================
# Workers' comp class rates — per-$100-of-payroll premium rates by class.
# ----------------------------------------------------------------------------
# Most states price workers' comp as a rate per $100 of payroll, by risk
# classification code, with the actual rate coming from the employer's
# carrier quote (there is no public table to ship). The operator enters
# their rates; the premium report prices the year's wages by class for the
# carrier's premium audit. Washington's per-hour L&I system is separate and
# already lives in the WA state engine.
# ============================================================================

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, func

from app.database import Base


class WCClassRate(Base):
    __tablename__ = "wc_class_rates"

    id = Column(Integer, primary_key=True, index=True)
    class_code = Column(String(20), nullable=False, index=True)
    state = Column(String(2), nullable=False)
    description = Column(String(200), nullable=True)
    # Premium rate per $100 of payroll, from the carrier's quote.
    rate_per_100 = Column(Numeric(10, 4), nullable=False, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
