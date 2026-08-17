# ============================================================================
# Payroll report library coverage.
# ----------------------------------------------------------------------------
# Pins the journal's per-stub columns + window totals (and that they foot),
# the deduction register's per-employee sums, and the contractor-payments
# report showing both payment paths separately.
# ============================================================================


def _create_employee(client, **overrides):
    body = {
        "first_name": "Pat",
        "last_name": "Worker",
        "pay_type": "hourly",
        "pay_rate": 25,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, emp_id, pay_date="2026-06-05"):
    r = client.post(
        "/api/payroll",
        json={
            "period_start": pay_date,
            "period_end": pay_date,
            "pay_date": pay_date,
            "stubs": [{"employee_id": emp_id, "hours": 80}],
        },
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert client.post(f"/api/payroll/{run['id']}/process").status_code == 200
    return run


def test_payroll_journal_foots(client, seed_accounts):
    a = _create_employee(client, first_name="Ava")
    b = _create_employee(client, first_name="Bo")
    _run(client, a["id"], "2026-06-05")
    _run(client, b["id"], "2026-06-19")
    _run(client, a["id"], "2026-08-01")  # outside the window

    r = client.get("/api/reports/payroll-journal?start=2026-06-01&end=2026-06-30")
    assert r.status_code == 200, r.text
    journal = r.json()
    assert len(journal["runs"]) == 2
    stubs = [s for run in journal["runs"] for s in run["stubs"]]
    assert journal["totals"]["gross"] == round(sum(s["gross"] for s in stubs), 2)
    assert journal["totals"]["net"] == round(sum(s["net"] for s in stubs), 2)
    assert journal["totals"]["gross"] == 4000.00  # 2 stubs x 80h x $25
    # Every run row carries its GL transaction id for reconciliation.
    assert all(run["transaction_id"] for run in journal["runs"])


def test_deduction_register(client, seed_accounts):
    emp = _create_employee(client)
    quiet = _create_employee(client, first_name="NoDed")
    client.post(
        "/api/deductions/garnishments",
        json={
            "employee_id": emp["id"],
            "garnishment_type": "creditor",
            "calc_method": "fixed",
            "amount": 75,
        },
    )
    _run(client, emp["id"])
    _run(client, quiet["id"])

    reg = client.get("/api/reports/deduction-register?year=2026").json()
    # Only the employee with actual deductions appears.
    assert [r["employee_id"] for r in reg["rows"]] == [emp["id"]]
    assert reg["rows"][0]["garnishments"] == 75.00
    assert reg["totals"]["garnishments"] == 75.00


def test_contractor_payments_report_shows_both_paths(client, seed_accounts):
    v = client.post(
        "/api/vendors", json={"name": "Rick", "is_1099_vendor": True}
    ).json()
    # AP path.
    bill = client.post(
        "/api/bills",
        json={
            "vendor_id": v["id"],
            "date": "2026-03-01",
            "due_date": "2026-03-01",
            "bill_number": "RPT-1",
            "lines": [
                {"description": "w", "quantity": 1, "rate": 400, "line_order": 0}
            ],
        },
    ).json()
    client.post(
        "/api/bill-payments",
        json={
            "vendor_id": v["id"],
            "date": "2026-03-01",
            "amount": 400,
            "method": "check",
            "allocations": [{"bill_id": bill["id"], "amount": 400}],
        },
    )
    # Contractor-run path.
    run = client.post(
        "/api/contractor-runs",
        json={
            "pay_date": "2026-04-01",
            "payments": [{"vendor_id": v["id"], "amount": 300}],
        },
    ).json()
    client.post(f"/api/contractor-runs/{run['id']}/process")

    report = client.get("/api/reports/contractor-payments?year=2026").json()
    row = report["rows"][0]
    assert row["ap_bill_payments"] == 400.00
    assert row["contractor_run_payments"] == 300.00
    assert row["total"] == 700.00
    assert report["total"] == 700.00
