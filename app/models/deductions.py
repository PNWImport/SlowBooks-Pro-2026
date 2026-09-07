# ============================================================================
# Garnishment orders — CCPA limits and multi-order priority.
# Voluntary deductions and benefits moved to the benefits engine
# (app/models/benefits.py): a benefit is a code with a rule, applied in
# sequence, with effective-dated rates and posted-run snapshots.
# ============================================================================

import enum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    Date,
    Enum,
    Boolean,
    ForeignKey,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.services.encryption import EncryptedString


class GarnishmentType(str, enum.Enum):
    CHILD_SUPPORT = "child_support"
    FEDERAL_LEVY = "federal_levy"
    STATE_TAX_LEVY = "state_tax_levy"
    STUDENT_LOAN = "student_loan"
    BANKRUPTCY = "bankruptcy"
    CREDITOR = "creditor"


class GarnishmentMethod(str, enum.Enum):
    FIXED = "fixed"
    PERCENT_DISPOSABLE = "percent_disposable"


class GarnishmentOrder(Base):
    __tablename__ = "garnishment_orders"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(
        Integer, ForeignKey("employees.id"), nullable=False, index=True
    )
    garnishment_type = Column(Enum(GarnishmentType), default=GarnishmentType.CREDITOR)
    calc_method = Column(Enum(GarnishmentMethod), default=GarnishmentMethod.FIXED)
    amount = Column(
        Numeric(12, 2), default=0
    )  # dollars (fixed) or percent (percent_disposable)

    priority = Column(Integer, default=0)
    case_number = Column(String(80), nullable=True)
    # Remittance target: who the withheld money is actually owed to. A
    # garnishment without an agency can still be withheld, but its
    # remittance rows will nag until the payee is filled in.
    agency_name = Column(String(200), nullable=True)
    # Where a garnishment is remitted. Identifies the order's nature (child
    # support, tax levy) by recipient, so it travels with the employee's PII.
    agency_address = Column(EncryptedString(500), nullable=True)
    remit_reference = Column(String(80), nullable=True)  # payee's case/remit id
    # Child-support CCPA modifiers.
    supports_secondary_family = Column(Boolean, default=False)
    in_arrears_12_weeks = Column(Boolean, default=False)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    employee = relationship("Employee")


class GarnishmentRemittance(Base):
    """One order's withholding from one processed pay run — money that must
    now be forwarded to the agency. Created automatically when a pay run
    processes; the operator marks rows remitted with a payment reference
    once the check/ACH actually goes out. The register endpoint lists what
    is still owed, so withheld-but-never-forwarded money — the classic
    small-employer garnishment failure — stays visible."""

    __tablename__ = "garnishment_remittances"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(
        Integer, ForeignKey("garnishment_orders.id"), nullable=False, index=True
    )
    pay_run_id = Column(Integer, ForeignKey("pay_runs.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=0)
    withheld_date = Column(Date, nullable=False)

    remitted_at = Column(DateTime(timezone=True), nullable=True)
    remit_payment_reference = Column(String(120), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("GarnishmentOrder")
    employee = relationship("Employee")
