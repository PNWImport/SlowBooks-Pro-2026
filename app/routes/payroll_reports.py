# ============================================================================
# Payroll report library — journal, deduction register, contractor payments.
# ----------------------------------------------------------------------------
# The reporting surface over data other features already write. Sibling
# reports live elsewhere and are not duplicated here: workers'-comp premium
# (/api/workers-comp/premium-report), tax liability calendar
# (/api/tax-forms/liability-calendar), SUI (/api/payroll/forms/sui),
# garnishment remittance register (/api/deductions/garnishments/remittances).
# Department / job-cost allocation needs a department dimension the app
# doesn't have — tracked in docs/todo.md.
# ============================================================================

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.payroll import PayRun, PayRunStatus, PayStub

router = APIRouter(prefix="/api/reports", tags=["payroll-reports"])

CENT = Decimal("0.01")


def _f(value) -> float:
    return float(Decimal(str(value or 0)).quantize(CENT))


@router.get("/payroll-journal")
def payroll_journal(
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
):
    """Every processed pay run in the window, itemized per employee.

    The columns an accountant reconciles against the GL: gross, each
    employee-side tax, deductions, garnishments, net; employer-side taxes
    alongside. Totals across the window at the bottom.
    """
    runs = (
        db.query(PayRun)
        .options(joinedload(PayRun.stubs).joinedload(PayStub.employee))
        .filter(
            PayRun.status == PayRunStatus.PROCESSED,
            PayRun.pay_date >= start,
            PayRun.pay_date <= end,
        )
        .order_by(PayRun.pay_date)
        .all()
    )

    totals = {
        key: Decimal("0")
        for key in (
            "gross",
            "federal",
            "state",
            "state_other",
            "local",
            "ss",
            "medicare",
            "pretax",
            "posttax",
            "garnishments",
            "net",
            "employer_taxes",
        )
    }
    out_runs = []
    for run in runs:
        rows = []
        for s in run.stubs:
            employer = (
                Decimal(str(s.employer_ss_tax or 0))
                + Decimal(str(s.employer_medicare_tax or 0))
                + Decimal(str(s.futa_tax or 0))
                + Decimal(str(s.suta_tax or 0))
                + Decimal(str(s.state_other_employer or 0))
                + Decimal(str(s.local_tax_employer or 0))
            )
            rows.append(
                {
                    "employee_id": s.employee_id,
                    "employee_name": s.employee.full_name if s.employee else None,
                    "gross": _f(s.gross_pay),
                    "federal": _f(s.federal_tax),
                    "state": _f(s.state_tax),
                    "state_other": _f(s.state_other_employee),
                    "local": _f(s.local_tax),
                    "ss": _f(s.ss_tax),
                    "medicare": _f(s.medicare_tax),
                    "pretax_deductions": _f(s.pretax_deductions),
                    "posttax_deductions": _f(s.posttax_deductions),
                    "garnishments": _f(s.garnishments),
                    "net": _f(s.net_pay),
                    "employer_taxes": _f(employer),
                }
            )
            totals["gross"] += Decimal(str(s.gross_pay or 0))
            totals["federal"] += Decimal(str(s.federal_tax or 0))
            totals["state"] += Decimal(str(s.state_tax or 0))
            totals["state_other"] += Decimal(str(s.state_other_employee or 0))
            totals["local"] += Decimal(str(s.local_tax or 0))
            totals["ss"] += Decimal(str(s.ss_tax or 0))
            totals["medicare"] += Decimal(str(s.medicare_tax or 0))
            totals["pretax"] += Decimal(str(s.pretax_deductions or 0))
            totals["posttax"] += Decimal(str(s.posttax_deductions or 0))
            totals["garnishments"] += Decimal(str(s.garnishments or 0))
            totals["net"] += Decimal(str(s.net_pay or 0))
            totals["employer_taxes"] += employer
        out_runs.append(
            {
                "pay_run_id": run.id,
                "pay_date": run.pay_date.isoformat(),
                "run_type": run.run_type.value if run.run_type else None,
                "transaction_id": run.transaction_id,
                "stubs": rows,
            }
        )

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "runs": out_runs,
        "totals": {key: _f(value) for key, value in totals.items()},
    }


@router.get("/deduction-register")
def deduction_register(year: int = Query(...), db: Session = Depends(get_db)):
    """Per-employee pre/post-tax deduction and garnishment totals for a year.

    The reconciliation view for benefit-provider invoices and 401(k)
    remittances: what was actually taken from checks, by person.
    """
    stubs = (
        db.query(PayStub)
        .join(PayRun, PayStub.pay_run_id == PayRun.id)
        .options(joinedload(PayStub.employee))
        .filter(
            PayRun.status == PayRunStatus.PROCESSED,
            PayRun.pay_date >= date(year, 1, 1),
            PayRun.pay_date <= date(year, 12, 31),
        )
        .all()
    )
    by_employee: dict[int, dict] = {}
    for s in stubs:
        entry = by_employee.setdefault(
            s.employee_id,
            {
                "employee_id": s.employee_id,
                "employee_name": s.employee.full_name if s.employee else None,
                "pretax": Decimal("0"),
                "posttax": Decimal("0"),
                "garnishments": Decimal("0"),
                "stub_count": 0,
            },
        )
        entry["pretax"] += Decimal(str(s.pretax_deductions or 0))
        entry["posttax"] += Decimal(str(s.posttax_deductions or 0))
        entry["garnishments"] += Decimal(str(s.garnishments or 0))
        entry["stub_count"] += 1

    rows = [
        {
            "employee_id": e["employee_id"],
            "employee_name": e["employee_name"],
            "pretax_deductions": _f(e["pretax"]),
            "posttax_deductions": _f(e["posttax"]),
            "garnishments": _f(e["garnishments"]),
            "stub_count": e["stub_count"],
        }
        for e in sorted(by_employee.values(), key=lambda e: e["employee_id"])
        if e["pretax"] or e["posttax"] or e["garnishments"]
    ]
    return {
        "year": year,
        "rows": rows,
        "totals": {
            "pretax_deductions": _f(sum(r["pretax_deductions"] for r in rows)),
            "posttax_deductions": _f(sum(r["posttax_deductions"] for r in rows)),
            "garnishments": _f(sum(r["garnishments"] for r in rows)),
        },
    }


@router.get("/contractor-payments")
def contractor_payments_report(year: int = Query(...), db: Session = Depends(get_db)):
    """Per-vendor contractor payments for a year, both payment paths.

    AP bill payments and processed contractor-run payments side by side —
    the same split the 1099-NEC totals sum, kept visible here so an
    operator can see WHICH path paid a vendor.
    """
    from sqlalchemy import func as safunc

    from app.models.bills import BillPayment
    from app.models.contacts import Vendor
    from app.models.contractor_payments import (
        ContractorPayment,
        ContractorPayRun,
        ContractorRunStatus,
    )

    start, end = date(year, 1, 1), date(year, 12, 31)
    ap = dict(
        db.query(BillPayment.vendor_id, safunc.sum(BillPayment.amount))
        .filter(BillPayment.date >= start, BillPayment.date <= end)
        .group_by(BillPayment.vendor_id)
        .all()
    )
    runs = dict(
        db.query(ContractorPayment.vendor_id, safunc.sum(ContractorPayment.amount))
        .join(ContractorPayRun, ContractorPayment.run_id == ContractorPayRun.id)
        .filter(
            ContractorPayRun.status == ContractorRunStatus.PROCESSED,
            ContractorPayRun.pay_date >= start,
            ContractorPayRun.pay_date <= end,
        )
        .group_by(ContractorPayment.vendor_id)
        .all()
    )

    vendor_ids = sorted(set(ap) | set(runs))
    vendors = {
        v.id: v for v in db.query(Vendor).filter(Vendor.id.in_(vendor_ids)).all()
    }
    rows = []
    for vid in vendor_ids:
        vendor = vendors.get(vid)
        ap_total = Decimal(str(ap.get(vid) or 0))
        run_total = Decimal(str(runs.get(vid) or 0))
        rows.append(
            {
                "vendor_id": vid,
                "vendor_name": vendor.name if vendor else None,
                "is_1099_vendor": bool(vendor and vendor.is_1099_vendor),
                "ap_bill_payments": _f(ap_total),
                "contractor_run_payments": _f(run_total),
                "total": _f(ap_total + run_total),
            }
        )
    return {
        "year": year,
        "rows": rows,
        "total": _f(sum(r["total"] for r in rows)),
    }
