# ============================================================================
# Contractor pay runs — paying 1099 contractors like a payroll batch.
# ----------------------------------------------------------------------------
# Contractors previously lived only in AP: create a bill, pay the bill. That
# works for invoices, but paying a roster of contractors every period wants
# the payroll shape — one dated run, many payees, one JE, one NACHA file —
# without any withholding math (1099 payees get gross; taxes are their
# problem, the 1099-NEC is ours).
#
# ContractorPayment rows feed the 1099-NEC totals alongside bill payments
# (see services/form_1099.py) and the vendor's direct-deposit account feeds
# the NACHA export.
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
from app.models.bank_accounts import BankAccountKind


class ContractorRunStatus(str, enum.Enum):
    DRAFT = "draft"
    PROCESSED = "processed"
    VOID = "void"


class ContractorPayRun(Base):
    __tablename__ = "contractor_pay_runs"

    id = Column(Integer, primary_key=True, index=True)
    pay_date = Column(Date, nullable=False)
    memo = Column(String(200), nullable=True)
    status = Column(Enum(ContractorRunStatus), default=ContractorRunStatus.DRAFT)
    total_amount = Column(Numeric(12, 2), default=0)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    transaction = relationship("Transaction", foreign_keys=[transaction_id])
    payments = relationship(
        "ContractorPayment",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class ContractorPayment(Base):
    __tablename__ = "contractor_payments"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer,
        ForeignKey("contractor_pay_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False, default=0)
    description = Column(String(200), nullable=True)

    run = relationship("ContractorPayRun", back_populates="payments")
    vendor = relationship("Vendor")


class VendorBankAccount(Base):
    """Direct-deposit destination for a contractor — the employee bank
    account pattern, minus split-deposit (one FULL account per vendor).
    Routing/account numbers are Fernet-encrypted at rest, last-4 clear."""

    __tablename__ = "vendor_bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False, index=True)

    nickname = Column(String(100), nullable=True)
    account_kind = Column(Enum(BankAccountKind), default=BankAccountKind.CHECKING)
    routing_number_enc = Column(String(255), nullable=True)
    account_number_enc = Column(String(255), nullable=True)
    account_last_four = Column(String(4), nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    vendor = relationship("Vendor")
