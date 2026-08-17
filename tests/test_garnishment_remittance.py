# ============================================================================
# Garnishment remittance coverage.
# ----------------------------------------------------------------------------
# The failure this feature exists to prevent: money withheld from a paycheck
# that never reaches the agency. Pins: remittance rows auto-created at
# pay-run processing (per order, correct amounts), the pending register
# (with agency-missing nagging), mark-remitted flow + idempotency, and that
# draft runs create nothing.
# ============================================================================

from decimal import Decimal


def _create_employee(client, **overrides):
    body = {
        "first_name": "Pat",
        "last_name": "Worker",
        "pay_type": "hourly",
        "pay_rate": 30,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _create_garnishment(client, emp_id, **overrides):
    body = {
        "employee_id": emp_id,
        "garnishment_type": "child_support",
        "calc_method": "fixed",
        "amount": 150,
        "priority": 1,
        "agency_name": "State Disbursement Unit",
        "agency_address": "PO Box 1, Olympia WA",
        "remit_reference": "CS-2026-777",
    }
    body.update(overrides)
    r = client.post("/api/deductions/garnishments", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _run_payroll(client, emp_id, pay_date="2026-06-05", process=True):
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
    if process:
        assert client.post(f"/api/payroll/{run['id']}/process").status_code == 200
    return run


def test_agency_fields_round_trip(client):
    emp = _create_employee(client)
    order = _create_garnishment(client, emp["id"])
    assert order["agency_name"] == "State Disbursement Unit"
    assert order["remit_reference"] == "CS-2026-777"


def test_processing_creates_remittance_rows(client, seed_accounts):
    emp = _create_employee(client)
    order = _create_garnishment(client, emp["id"], amount=150)
    run = _run_payroll(client, emp["id"])

    register = client.get("/api/deductions/garnishments/remittances").json()
    assert register["total_pending"] == 150.00
    row = register["rows"][0]
    assert row["order_id"] == order["id"]
    assert row["pay_run_id"] == run["id"]
    assert row["agency_name"] == "State Disbursement Unit"
    assert row["agency_missing"] is False
    assert row["garnishment_type"] == "child_support"
    assert row["withheld_date"] == "2026-06-05"


def test_two_orders_two_rows(client, seed_accounts):
    emp = _create_employee(client)
    _create_garnishment(client, emp["id"], amount=100, priority=1)
    _create_garnishment(
        client,
        emp["id"],
        amount=50,
        priority=2,
        garnishment_type="student_loan",
        agency_name="ED Servicer",
    )
    _run_payroll(client, emp["id"])
    register = client.get("/api/deductions/garnishments/remittances").json()
    assert len(register["rows"]) == 2
    assert register["total_pending"] == 150.00


def test_missing_agency_is_flagged_not_blocked(client, seed_accounts):
    emp = _create_employee(client)
    _create_garnishment(client, emp["id"], agency_name=None, remit_reference=None)
    _run_payroll(client, emp["id"])
    register = client.get("/api/deductions/garnishments/remittances").json()
    assert register["rows"][0]["agency_missing"] is True


def test_draft_run_creates_no_rows(client, seed_accounts):
    emp = _create_employee(client)
    _create_garnishment(client, emp["id"])
    _run_payroll(client, emp["id"], process=False)
    register = client.get("/api/deductions/garnishments/remittances?status=all").json()
    assert register["rows"] == []


def test_no_garnishment_no_rows(client, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"])
    register = client.get("/api/deductions/garnishments/remittances?status=all").json()
    assert register["rows"] == []


def test_mark_remitted_flow(client, seed_accounts):
    emp = _create_employee(client)
    _create_garnishment(client, emp["id"], amount=150)
    _run_payroll(client, emp["id"])
    row_id = client.get("/api/deductions/garnishments/remittances").json()["rows"][0][
        "id"
    ]

    r = client.post(
        f"/api/deductions/garnishments/remittances/{row_id}/mark-remitted",
        json={"payment_reference": "CHK-9001"},
    )
    assert r.status_code == 200, r.text

    pending = client.get("/api/deductions/garnishments/remittances").json()
    assert pending["rows"] == []
    assert pending["total_pending"] == 0

    remitted = client.get(
        "/api/deductions/garnishments/remittances?status=remitted"
    ).json()
    assert remitted["rows"][0]["remit_payment_reference"] == "CHK-9001"

    # Double-remit rejected; unknown id 404; bad status 400.
    r = client.post(
        f"/api/deductions/garnishments/remittances/{row_id}/mark-remitted",
        json={"payment_reference": "CHK-9002"},
    )
    assert r.status_code == 400
    assert (
        client.post(
            "/api/deductions/garnishments/remittances/999/mark-remitted",
            json={"payment_reference": "X"},
        ).status_code
        == 404
    )
    assert (
        client.get("/api/deductions/garnishments/remittances?status=bogus").status_code
        == 400
    )


def test_percent_disposable_amount_matches_stub(client, seed_accounts):
    """Remittance amount equals what the stub actually withheld."""
    emp = _create_employee(client)
    _create_garnishment(client, emp["id"], calc_method="percent_disposable", amount=10)
    run = _run_payroll(client, emp["id"])
    stub_garnish = run["stubs"][0]["garnishments"]
    register = client.get("/api/deductions/garnishments/remittances").json()
    assert register["rows"][0]["amount"] == stub_garnish
    assert register["rows"][0]["amount"] > 0
