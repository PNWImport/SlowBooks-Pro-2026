"""N+1 regression coverage on the list endpoints.

Pre-fix: GET /api/invoices returned `list[InvoiceResponse]`, and Pydantic's
model_validate read `inv.customer` and `inv.lines` for every row in the
loop. Those are lazy relationships, so a 500-row list page fired 1001
follow-up SELECTs against the DB. Same pattern across bills, POs,
payments, credit memos, and estimates.

Each test seeds N parent rows + their children, hits the list endpoint,
and asserts the total query count is bounded by a small constant rather
than scaling with N. We use SQLAlchemy's `before_cursor_execute` event to
count SELECTs — durable across SQLAlchemy versions and DB dialects.
"""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from sqlalchemy import event


@contextmanager
def _count_selects(engine):
    """Yield a list whose len() is the number of SELECT statements run
    against `engine` while the context is open."""
    statements = []

    def _hook(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _hook)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _hook)


N_ROWS = 8  # enough to expose linear growth without slowing the suite
MAX_QUERIES = 6  # parent SELECT + a fixed number of eager-load/auth queries


def test_analytics_dashboard_query_plan_is_constant(db_session, db_engine):
    """The complete analytics snapshot must remain ten aggregate queries.

    This checks the engine directly so session-authentication queries do not
    obscure the dashboard's own database cost.
    """
    from app.services.analytics import AnalyticsEngine

    with _count_selects(db_engine) as stmts:
        payload = AnalyticsEngine(db_session).get_dashboard(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
        )

    assert set(payload) == {
        "revenue_by_customer",
        "revenue_trend",
        "expenses_by_category",
        "ar_aging",
        "ap_aging",
        "dso",
        "cash_forecast",
        "customer_profit",
    }
    assert len(stmts) == 10, "\n".join(stmts)


def _seed_invoices(db_session, customer_id, n):
    from app.models.invoices import Invoice, InvoiceLine

    for i in range(n):
        inv = Invoice(
            invoice_number=f"N1-{i:04d}",
            customer_id=customer_id,
            date=date(2026, 5, 1),
            subtotal=Decimal("100"),
            tax_rate=Decimal("0"),
            tax_amount=Decimal("0"),
            total=Decimal("100"),
            balance_due=Decimal("100"),
        )
        db_session.add(inv)
        db_session.flush()
        db_session.add(
            InvoiceLine(
                invoice_id=inv.id,
                description=f"L{i}",
                quantity=Decimal("1"),
                rate=Decimal("100"),
                amount=Decimal("100"),
                line_order=0,
            )
        )
    db_session.commit()


def test_list_invoices_query_count_constant(
    client, db_session, db_engine, seed_accounts, seed_customer
):
    _seed_invoices(db_session, seed_customer.id, N_ROWS)

    with _count_selects(db_engine) as stmts:
        r = client.get("/api/invoices")

    assert r.status_code == 200, r.text
    assert len(r.json()) == N_ROWS
    # Pre-fix this would be roughly 1 + 2*N_ROWS. With joinedload+selectinload
    # we expect 1 (parent SELECT with customer JOIN) + 1 (lines IN-clause) +
    # auth/session/audit overhead. Cap at MAX_QUERIES so any future
    # regression linear in N_ROWS lights this up.
    assert len(stmts) <= MAX_QUERIES, (
        f"got {len(stmts)} SELECTs for {N_ROWS} invoices " f"(expected ~{MAX_QUERIES})"
    )


def _seed_bills(db_session, vendor_id, n):
    from app.models.bills import Bill, BillLine

    for i in range(n):
        b = Bill(
            bill_number=f"BN1-{i:04d}",
            vendor_id=vendor_id,
            date=date(2026, 5, 1),
            subtotal=Decimal("100"),
            tax_rate=Decimal("0"),
            tax_amount=Decimal("0"),
            total=Decimal("100"),
            balance_due=Decimal("100"),
        )
        db_session.add(b)
        db_session.flush()
        db_session.add(
            BillLine(
                bill_id=b.id,
                description=f"L{i}",
                quantity=Decimal("1"),
                rate=Decimal("100"),
                amount=Decimal("100"),
                line_order=0,
            )
        )
    db_session.commit()


def test_list_bills_query_count_constant(client, db_session, db_engine, seed_accounts):
    from app.models.contacts import Vendor

    v = Vendor(name="V", is_active=True)
    db_session.add(v)
    db_session.commit()

    _seed_bills(db_session, v.id, N_ROWS)

    with _count_selects(db_engine) as stmts:
        r = client.get("/api/bills")

    assert r.status_code == 200, r.text
    assert len(r.json()) == N_ROWS
    assert len(stmts) <= MAX_QUERIES, f"got {len(stmts)} SELECTs for {N_ROWS} bills"


def test_list_purchase_orders_query_count_constant(client, db_session, db_engine):
    from app.models.contacts import Vendor
    from app.models.purchase_orders import PurchaseOrder, PurchaseOrderLine

    vendor = Vendor(name="N1 PO Vendor", is_active=True)
    db_session.add(vendor)
    db_session.flush()
    for i in range(N_ROWS):
        po = PurchaseOrder(
            po_number=f"PON1-{i:04d}",
            vendor_id=vendor.id,
            date=date(2026, 5, 1),
            subtotal=Decimal("10"),
            total=Decimal("10"),
        )
        db_session.add(po)
        db_session.flush()
        db_session.add(
            PurchaseOrderLine(
                purchase_order_id=po.id,
                description=f"L{i}",
                quantity=Decimal("1"),
                rate=Decimal("10"),
                amount=Decimal("10"),
                line_order=0,
            )
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/purchase-orders")

    assert response.status_code == 200, response.text
    assert len(response.json()) == N_ROWS
    assert len(stmts) <= MAX_QUERIES, f"got {len(stmts)} SELECTs for purchase orders"


def test_list_payments_query_count_constant(
    client, db_session, db_engine, seed_customer
):
    from app.models.invoices import Invoice
    from app.models.payments import Payment, PaymentAllocation

    invoice = Invoice(
        invoice_number="PAY-N1-INVOICE",
        customer_id=seed_customer.id,
        date=date(2026, 5, 1),
        subtotal=Decimal("100"),
        tax_rate=Decimal("0"),
        tax_amount=Decimal("0"),
        total=Decimal("100"),
        balance_due=Decimal("100"),
    )
    db_session.add(invoice)
    db_session.flush()
    for i in range(N_ROWS):
        payment = Payment(
            customer_id=seed_customer.id,
            date=date(2026, 5, 2),
            amount=Decimal("1"),
        )
        db_session.add(payment)
        db_session.flush()
        db_session.add(
            PaymentAllocation(
                payment_id=payment.id,
                invoice_id=invoice.id,
                amount=Decimal("1"),
            )
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/payments")

    assert response.status_code == 200, response.text
    assert len(response.json()) == N_ROWS
    assert len(stmts) <= MAX_QUERIES, f"got {len(stmts)} SELECTs for payments"


def test_list_credit_memos_query_count_constant(
    client, db_session, db_engine, seed_customer
):
    from app.models.credit_memos import CreditMemo, CreditMemoLine

    for i in range(N_ROWS):
        memo = CreditMemo(
            memo_number=f"CMN1-{i:04d}",
            customer_id=seed_customer.id,
            date=date(2026, 5, 1),
            subtotal=Decimal("10"),
            total=Decimal("10"),
            balance_remaining=Decimal("10"),
        )
        db_session.add(memo)
        db_session.flush()
        db_session.add(
            CreditMemoLine(
                credit_memo_id=memo.id,
                description=f"L{i}",
                quantity=Decimal("1"),
                rate=Decimal("10"),
                amount=Decimal("10"),
                line_order=0,
            )
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/credit-memos")

    assert response.status_code == 200, response.text
    assert len(response.json()) == N_ROWS
    assert len(stmts) <= MAX_QUERIES, f"got {len(stmts)} SELECTs for credit memos"


def test_list_estimates_query_count_constant(
    client, db_session, db_engine, seed_customer
):
    from app.models.estimates import Estimate, EstimateLine

    for i in range(N_ROWS):
        estimate = Estimate(
            estimate_number=f"ESTN1-{i:04d}",
            customer_id=seed_customer.id,
            date=date(2026, 5, 1),
            subtotal=Decimal("10"),
            tax_rate=Decimal("0"),
            tax_amount=Decimal("0"),
            total=Decimal("10"),
        )
        db_session.add(estimate)
        db_session.flush()
        db_session.add(
            EstimateLine(
                estimate_id=estimate.id,
                description=f"L{i}",
                quantity=Decimal("1"),
                rate=Decimal("10"),
                amount=Decimal("10"),
                line_order=0,
            )
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/estimates")

    assert response.status_code == 200, response.text
    assert len(response.json()) == N_ROWS
    assert len(stmts) <= MAX_QUERIES, f"got {len(stmts)} SELECTs for estimates"


def test_list_journal_entries_query_count_constant(
    client, db_session, db_engine, seed_accounts
):
    from app.models.transactions import Transaction, TransactionLine

    debit_id = seed_accounts["1010"].id
    credit_id = seed_accounts["4000"].id
    for i in range(N_ROWS):
        transaction = Transaction(
            date=date(2026, 5, 1),
            description=f"N1 journal {i}",
            source_type="manual",
        )
        db_session.add(transaction)
        db_session.flush()
        db_session.add_all(
            [
                TransactionLine(
                    transaction_id=transaction.id,
                    account_id=debit_id,
                    debit=Decimal("10"),
                    credit=Decimal("0"),
                ),
                TransactionLine(
                    transaction_id=transaction.id,
                    account_id=credit_id,
                    debit=Decimal("0"),
                    credit=Decimal("10"),
                ),
            ]
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/journal")

    assert response.status_code == 200, response.text
    assert len(response.json()) == N_ROWS
    assert len(stmts) <= MAX_QUERIES, f"got {len(stmts)} SELECTs for journal entries"
    assert len(client.get("/api/journal?skip=2&limit=3").json()) == 3


def test_list_bill_payments_query_count_constant(client, db_session, db_engine):
    from app.models.bills import BillPayment
    from app.models.contacts import Vendor

    for i in range(N_ROWS):
        vendor = Vendor(name=f"N1 Payment Vendor {i}", is_active=True)
        db_session.add(vendor)
        db_session.flush()
        db_session.add(
            BillPayment(
                vendor_id=vendor.id,
                date=date(2026, 5, 1),
                amount=Decimal("10"),
            )
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/bill-payments")

    assert response.status_code == 200, response.text
    assert len(response.json()) == N_ROWS
    assert len(stmts) <= MAX_QUERIES, f"got {len(stmts)} SELECTs for bill payments"
    assert len(client.get("/api/bill-payments?skip=2&limit=3").json()) == 3


def test_list_recurring_invoices_query_count_constant(client, db_session, db_engine):
    from app.models.contacts import Customer
    from app.models.recurring import RecurringInvoice, RecurringInvoiceLine

    for i in range(N_ROWS):
        customer = Customer(name=f"N1 Recurring Customer {i}", is_active=True)
        db_session.add(customer)
        db_session.flush()
        recurring = RecurringInvoice(
            customer_id=customer.id,
            frequency="monthly",
            start_date=date(2026, 5, 1),
            next_due=date(2026, 6, 1),
        )
        db_session.add(recurring)
        db_session.flush()
        db_session.add(
            RecurringInvoiceLine(
                recurring_invoice_id=recurring.id,
                description=f"L{i}",
                quantity=Decimal("1"),
                rate=Decimal("10"),
                line_order=0,
            )
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/recurring")

    assert response.status_code == 200, response.text
    assert len(response.json()) == N_ROWS
    assert len(stmts) <= MAX_QUERIES, f"got {len(stmts)} SELECTs for recurring invoices"
    assert len(client.get("/api/recurring?skip=2&limit=3").json()) == 3


def test_list_job_costs_query_count_constant(
    client, db_session, db_engine, seed_accounts
):
    from app.models.contacts import Customer
    from app.models.cost_codes import CostCode
    from app.models.job_costing import JobCost, JobCostLine
    from app.models.jobs import Job

    debit_id = seed_accounts["5000"].id
    credit_id = seed_accounts["1010"].id
    cost_code = CostCode(code="N1-JC", name="N1 job cost", cost_type="labor")
    db_session.add(cost_code)
    db_session.flush()
    for i in range(N_ROWS):
        customer = Customer(name=f"N1 Job Customer {i}", is_active=True)
        db_session.add(customer)
        db_session.flush()
        job = Job(customer_id=customer.id, name=f"N1 Job {i}")
        db_session.add(job)
        db_session.flush()
        job_cost = JobCost(
            number=f"JCN1-{i:04d}",
            date=date(2026, 5, 1),
            job_id=job.id,
            total=Decimal("10"),
        )
        db_session.add(job_cost)
        db_session.flush()
        db_session.add(
            JobCostLine(
                job_cost_id=job_cost.id,
                job_id=job.id,
                cost_code_id=cost_code.id,
                quantity=Decimal("1"),
                rate=Decimal("10"),
                amount=Decimal("10"),
                debit_account_id=debit_id,
                credit_account_id=credit_id,
            )
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/job-costs")

    assert response.status_code == 200, response.text
    assert len(response.json()) == N_ROWS
    assert len(stmts) <= MAX_QUERIES, f"got {len(stmts)} SELECTs for job costs"
    assert len(client.get("/api/job-costs?skip=2&limit=3").json()) == 3


def test_list_esign_envelopes_is_bounded(client, db_session, db_engine):
    from app.models.esign import SignatureEnvelope
    from app.models.payroll import Employee

    for i in range(N_ROWS):
        employee = Employee(
            first_name=f"Signer{i}",
            last_name="N1",
            ssn_last_four=f"{i:04d}",
            pay_type="hourly",
            pay_rate=Decimal("25"),
            pay_frequency="biweekly",
            filing_status="single",
            is_active=True,
        )
        db_session.add(employee)
        db_session.flush()
        db_session.add(
            SignatureEnvelope(
                employee_id=employee.id,
                title=f"N1 envelope {i}",
                body="Synthetic document",
                content_hash=f"{i:064x}",
            )
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/esign?skip=2&limit=3")

    assert response.status_code == 200, response.text
    assert len(response.json()) == 3
    assert len(stmts) <= MAX_QUERIES, f"got {len(stmts)} SELECTs for e-sign"


def _seed_employee(db_session):
    from app.models.payroll import Employee

    emp = Employee(
        first_name="N1",
        last_name="Worker",
        ssn_last_four="0000",
        pay_type="hourly",
        pay_rate=Decimal("25"),
        pay_frequency="biweekly",
        filing_status="single",
        is_active=True,
    )
    db_session.add(emp)
    db_session.commit()
    return emp


def _seed_time_entries(db_session, employee_id, customer_id, n):
    from app.models.cost_codes import CostCode
    from app.models.jobs import Job
    from app.models.time_entries import TimeEntry

    for i in range(n):
        job = Job(customer_id=customer_id, name=f"N1 job {i}")
        code = CostCode(code=f"N1-{i}", name=f"N1 code {i}", cost_type="labor")
        db_session.add_all([job, code])
        db_session.flush()
        db_session.add(
            TimeEntry(
                employee_id=employee_id,
                date=date(2026, 5, 1),
                hours_regular=Decimal("8"),
                hours_overtime=Decimal("0"),
                hours_doubletime=Decimal("0"),
                job_id=job.id,
                cost_code_id=code.id,
            )
        )
    db_session.commit()


def test_list_time_entries_query_count_constant(
    client, db_session, db_engine, seed_customer
):
    emp = _seed_employee(db_session)
    _seed_time_entries(db_session, emp.id, seed_customer.id, N_ROWS)

    with _count_selects(db_engine) as stmts:
        r = client.get("/api/time-entries")

    assert r.status_code == 200, r.text
    assert len(r.json()) == N_ROWS
    # Pre-fix _resp() read entry.employee per row -> 1 + N SELECTs. With
    # joinedload(TimeEntry.employee) the employee comes back in the parent
    # SELECT, so the count stays bounded regardless of N_ROWS.
    assert (
        len(stmts) <= MAX_QUERIES
    ), f"got {len(stmts)} SELECTs for {N_ROWS} time entries\n" + "\n".join(stmts)


def _seed_pto_requests(db_session, employee_id, n):
    from app.models.pto import PTORequest, PTOType

    for i in range(n):
        db_session.add(
            PTORequest(
                employee_id=employee_id,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 2),
                hours=Decimal("8"),
                pto_type=PTOType.VACATION,
            )
        )
    db_session.commit()


def test_list_pto_requests_query_count_constant(client, db_session, db_engine):
    emp = _seed_employee(db_session)
    _seed_pto_requests(db_session, emp.id, N_ROWS)

    with _count_selects(db_engine) as stmts:
        r = client.get("/api/pto/requests")

    assert r.status_code == 200, r.text
    assert len(r.json()) == N_ROWS
    # Pre-fix list_requests read req.employee.full_name per row -> 1 + N
    # SELECTs. joinedload(PTORequest.employee) collapses that to the parent
    # SELECT, keeping the count bounded regardless of N_ROWS.
    assert (
        len(stmts) <= MAX_QUERIES
    ), f"got {len(stmts)} SELECTs for {N_ROWS} pto requests"


def test_list_pay_runs_preloads_stubs_employees_and_benefits(
    client, db_session, db_engine
):
    from app.models.benefits import PayStubBenefit
    from app.models.payroll import PayRun, PayStub

    employee = _seed_employee(db_session)
    for i in range(N_ROWS):
        run = PayRun(
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 15),
            pay_date=date(2026, 5, 20),
        )
        db_session.add(run)
        db_session.flush()
        stub = PayStub(pay_run_id=run.id, employee_id=employee.id)
        db_session.add(stub)
        db_session.flush()
        db_session.add(
            PayStubBenefit(
                pay_stub_id=stub.id,
                code=f"N1-{i}",
                name=f"Benefit {i}",
                kind="deduction",
                category="posttax",
                calc_method="fixed",
            )
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/payroll")

    assert response.status_code == 200, response.text
    assert len(response.json()) == N_ROWS
    assert all(len(run["stubs"][0]["benefits"]) == 1 for run in response.json())
    assert (
        len(stmts) <= MAX_QUERIES
    ), f"got {len(stmts)} SELECTs for {N_ROWS} pay runs\n" + "\n".join(stmts)


def test_list_garnishment_remittances_query_count_constant(
    client, db_session, db_engine
):
    from app.models.deductions import GarnishmentOrder, GarnishmentRemittance
    from app.models.payroll import PayRun

    employee = _seed_employee(db_session)
    pay_run = PayRun(
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 15),
        pay_date=date(2026, 5, 20),
    )
    db_session.add(pay_run)
    db_session.flush()
    for i in range(N_ROWS):
        order = GarnishmentOrder(
            employee_id=employee.id,
            amount=Decimal("5"),
            agency_name=f"Agency {i}",
        )
        db_session.add(order)
        db_session.flush()
        db_session.add(
            GarnishmentRemittance(
                order_id=order.id,
                pay_run_id=pay_run.id,
                employee_id=employee.id,
                amount=Decimal("5"),
                withheld_date=date(2026, 5, 20),
            )
        )
    db_session.commit()

    with _count_selects(db_engine) as stmts:
        response = client.get("/api/deductions/garnishments/remittances?status=all")

    assert response.status_code == 200, response.text
    assert len(response.json()["rows"]) == N_ROWS
    assert (
        len(stmts) <= MAX_QUERIES
    ), f"got {len(stmts)} SELECTs for garnishment remittances\n" + "\n".join(stmts)

    page = client.get(
        "/api/deductions/garnishments/remittances?status=all&skip=2&limit=3"
    )
    assert page.status_code == 200, page.text
    assert len(page.json()["rows"]) == 3
    assert page.json()["total_pending"] == N_ROWS * 5


# ── Nonprofit documents ───────────────────────────────────────────────────


def _seed_nonprofit_docs(client, n):
    funds = [
        client.post(
            "/api/classes",
            json={"name": f"Fund {i}", "restriction": "temporarily_restricted"},
        ).json()
        for i in range(n)
    ]
    for i, f in enumerate(funds):
        r = client.post(
            "/api/nonprofit/allocation-rules",
            json={
                "name": f"Rule {i}",
                "targets": [
                    {"class_id": f["id"], "function": "program", "weight": 70},
                    {"function": "management", "weight": 30},
                ],
            },
        )
        assert r.status_code == 201, r.text
        r = client.post(
            "/api/nonprofit/releases",
            json={"date": "2026-06-30", "class_id": f["id"], "amount": "10"},
        )
        assert r.status_code == 201, r.text


def test_list_nonprofit_documents_query_count_constant(
    client, db_session, db_engine, seed_accounts
):
    _seed_nonprofit_docs(client, N_ROWS)
    for path, cap in (
        ("/api/nonprofit/allocation-rules", MAX_QUERIES),
        ("/api/nonprofit/releases", MAX_QUERIES),
        ("/api/nonprofit/allocations", MAX_QUERIES),
    ):
        with _count_selects(db_engine) as stmts:
            r = client.get(path)
        assert r.status_code == 200, r.text
        assert len(stmts) <= cap, f"{path}: {len(stmts)} SELECTs\n" + "\n".join(stmts)


def test_list_in_kind_gifts_query_count_constant(
    client, db_session, db_engine, seed_accounts, seed_customer
):
    checking = seed_accounts["1010"].id
    for i in range(N_ROWS):
        r = client.post(
            "/api/in-kind-gifts",
            json={
                "customer_id": seed_customer.id,
                "date": "2026-04-20",
                "lines": [
                    {
                        "description": f"Item {i}",
                        "quantity": 1,
                        "fair_value": "10",
                        "debit_account_id": checking,
                    }
                ],
            },
        )
        assert r.status_code == 201, r.text
    with _count_selects(db_engine) as stmts:
        r = client.get("/api/in-kind-gifts")
    assert r.status_code == 200
    assert len(stmts) <= MAX_QUERIES, "\n".join(stmts)
