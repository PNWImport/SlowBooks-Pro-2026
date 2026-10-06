# ============================================================================
# Form 940 — Employer's Annual Federal Unemployment (FUTA) Tax Return
# ----------------------------------------------------------------------------
# Aggregates a full calendar year of PROCESSED pay stubs into the FUTA wage
# and tax totals reported on IRS Form 940. FUTA wages are capped at the first
# $7,000 paid to each employee for the year.
# ============================================================================

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import joinedload, selectinload

from app.models.payroll import PayRun, PayStub, PayRunStatus
from app.services.accounting import _q
from app.services.payroll_service import FUTA_WAGE_BASE
from app.services.pdf_service import _jinja_env, render_pdf
from app.services.payroll_wages import fica_wages, gross_wages


def _year_stubs(db, year: int) -> list[PayStub]:
    """All PROCESSED pay stubs with a pay_date inside the calendar year."""
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    return (
        db.query(PayStub)
        .join(PayRun, PayStub.pay_run_id == PayRun.id)
        .options(
            joinedload(PayStub.pay_run),
            joinedload(PayStub.employee),
            selectinload(PayStub.benefits),
        )
        .filter(PayRun.status == PayRunStatus.PROCESSED)
        .filter(PayRun.pay_date >= start)
        .filter(PayRun.pay_date <= end)
        .all()
    )


def compute_940(db, year: int) -> dict:
    """Aggregate annual Form 940 (FUTA) totals.

    FUTA taxable wages exclude recorded qualifying employee benefits, then
    apply each employee's $7,000 base. Benefit exemptions and excess wages
    are separate IRS lines.
    """
    stubs = _year_stubs(db, year)

    total_payments = Decimal("0")
    futa_tax = Decimal("0")
    exempt_payments = Decimal("0")
    # The cap applies to taxable wages after recorded qualified exclusions.
    paid_by_employee: dict[int, Decimal] = {}
    taxable_by_employee: dict[int, Decimal] = {}

    # Process in pay_date order so the per-employee wage base fills correctly.
    for s in sorted(stubs, key=lambda x: (x.pay_run.pay_date, x.id)):
        emp_id = s.employee_id
        gross = gross_wages(s)
        futa_wages = fica_wages(s)
        total_payments += gross
        exempt_payments += gross - futa_wages
        futa_tax += Decimal(str(s.futa_tax or 0))

        prior = paid_by_employee.get(emp_id, Decimal("0"))
        if prior >= FUTA_WAGE_BASE:
            taxable = Decimal("0")
        elif prior + futa_wages > FUTA_WAGE_BASE:
            taxable = FUTA_WAGE_BASE - prior
        else:
            taxable = futa_wages
        paid_by_employee[emp_id] = prior + futa_wages
        taxable_by_employee[emp_id] = (
            taxable_by_employee.get(emp_id, Decimal("0")) + taxable
        )

    total_taxable = sum(taxable_by_employee.values(), Decimal("0"))
    # IRS lines 4 and 5 distinguish qualifying exemptions from wages over cap.
    excess_payments = total_payments - exempt_payments - total_taxable

    return {
        "year": year,
        # Employees who received wages: a $0.00 stub pays no one.
        "num_employees": len({s.employee_id for s in stubs if gross_wages(s) > 0}),
        "num_stubs": len(stubs),
        # Line 3 — total payments to all employees
        "total_payments": _q(total_payments),
        # Line 4 — qualifying employee benefit exclusions
        "exempt_payments": _q(exempt_payments),
        # Line 5 — taxable wages paid above the $7,000 per-employee base
        "excess_payments": _q(excess_payments),
        # Line 7 — total FUTA taxable wages
        "futa_taxable_wages": _q(total_taxable),
        "futa_wage_base": FUTA_WAGE_BASE,
        # Line 8 — FUTA tax for the year
        "total_futa_tax": _q(futa_tax),
    }


def generate_940_pdf(db, year: int, company: dict, audit: dict | None = None) -> bytes:
    """Render Form 940 to a PDF for the given year."""
    data = compute_940(db, year)
    template = _jinja_env.get_template("form_940.html")
    html_str = template.render(data=data, company=company or {}, audit=audit or {})
    return render_pdf(html_str)
