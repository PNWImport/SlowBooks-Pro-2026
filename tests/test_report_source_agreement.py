"""Reports that must agree with the page they summarise: the 1099 Summary
with the 1099-NEC, and the dashboard Total Payables card with A/P aging."""

from datetime import date
from decimal import Decimal

from app.models.bills import Bill, BillPayment, BillStatus
from app.models.contacts import Vendor
from app.models.contractor_payments import (
    ContractorPayment,
    ContractorPayRun,
    ContractorRunStatus,
)
from app.models.vendor_credits import VendorCredit, VendorCreditStatus


def test_1099_summary_matches_the_nec_form_with_contractor_runs(client, db_session):
    v = Vendor(name="Both Paths LLC", is_1099_vendor=True)
    db_session.add(v)
    db_session.flush()
    db_session.add(
        BillPayment(vendor_id=v.id, date=date(2026, 3, 1), amount=Decimal("315.50"))
    )
    db_session.add(  # voided: counts toward neither
        BillPayment(
            vendor_id=v.id, date=date(2026, 3, 2), amount=Decimal("99"), is_voided=True
        )
    )
    done = ContractorPayRun(
        pay_date=date(2026, 4, 1), status=ContractorRunStatus.PROCESSED
    )
    voided = ContractorPayRun(
        pay_date=date(2026, 4, 2), status=ContractorRunStatus.VOID
    )
    db_session.add_all([done, voided])
    db_session.flush()
    for run, amt in ((done, "1500"), (voided, "700")):
        db_session.add(
            ContractorPayment(run_id=run.id, vendor_id=v.id, amount=Decimal(amt))
        )
    db_session.commit()

    summary = client.get("/api/reports/1099-summary?year=2026").json()
    row = next(i for i in summary["items"] if i["vendor_id"] == v.id)
    from app.services.form_1099 import compute_1099_data

    form = next(
        d for d in compute_1099_data(db_session, 2026) if d["vendor_id"] == v.id
    )
    assert row["total_paid"] == float(form["total_paid"]) == 1815.5
    assert row["above_threshold"] is True and form["reportable"] is True


def test_dashboard_payables_nets_unapplied_vendor_credit(client, db_session):
    v = Vendor(name="Credit Holder")
    db_session.add(v)
    db_session.flush()
    db_session.add(
        Bill(
            bill_number="B1",
            vendor_id=v.id,
            status=BillStatus.UNPAID,
            date=date.today(),
            due_date=date.today(),
            total=Decimal("300"),
            balance_due=Decimal("300"),
        )
    )
    db_session.add(
        VendorCredit(
            credit_number="VC1",
            vendor_id=v.id,
            status=VendorCreditStatus.ISSUED,
            date=date.today(),
            total=Decimal("50"),
            balance_remaining=Decimal("50"),
        )
    )
    db_session.commit()
    aging = client.get("/api/reports/ap-aging").json()["totals"]["total"]
    card = client.get("/api/dashboard/data?ids=payables").json()["payables"]["total"]
    assert aging == 250.0
    assert card == aging
