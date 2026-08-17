# ============================================================================
# Work locations — first-class places of work with a tax jurisdiction.
# ----------------------------------------------------------------------------
# Before this, an employee's tax situs lived in two free-typed columns
# (work_state, work_locality) with no shared source of truth: opening a
# second office meant editing every employee. A WorkLocation pins the
# address + jurisdiction once; employees attach to it, and jurisdiction
# resolution prefers explicit per-employee/per-stub values but falls back
# to the location's (see routes/payroll.py).
# ============================================================================

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from app.database import Base


class WorkLocation(Base):
    __tablename__ = "work_locations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    address1 = Column(String(200), nullable=True)
    address2 = Column(String(200), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(2), nullable=False)  # tax jurisdiction: state
    zip = Column(String(20), nullable=True)
    # Local tax jurisdiction code (app/services/local_tax/localities/), when
    # the location sits inside one — e.g. "PA-PHILADELPHIA".
    locality = Column(String(40), nullable=True)
    # Default workers'-comp class code for employees at this location.
    default_wc_class_code = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
