# ============================================================================
# Contractor pay-run coverage.
# ----------------------------------------------------------------------------
# The payroll shape for 1099 payees: batch create -> process (JE) -> NACHA.
# Pins the JE balance, the closing-date guard, the void/idempotency guards,
# the encrypted vendor bank store (one active account per vendor), the NACHA
# skip-if-no-account behavior, and — the point of the feature — contractor
# payments joining bill payments in the 1099-NEC totals.
# ============================================================================

from decimal import Decimal

from app.services.form_1099 import compute_1099_data


def _create_vendor(client, **overrides):
    body = {"name": "Rick Contractor", "is_1099_vendor": True, "tax_id": "12-3456789"}
    body.update(overrides)
    r = client.post("/api/vendors", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _create_run(client, payments, pay_date="2026-06-05", memo=None):
    r = client.post(
        "/api/contractor-runs",
        json={"pay_date": pay_date, "memo": memo, "payments": payments},
    )
    assert r.status_code == 201, r.text
    return r.json()


ORIGINATING = {
    "immediate_destination": "021000021",
    "immediate_origin": "9111234567",
    "originating_dfi_id": "02100002",
    "company_account": "123456789",
    "company_name": "SLOWBOOKS TEST",
    "company_id": "911234567",
}


# --- create -----------------------------------------------------------------


def test_create_run_totals_payments(client, seed_accounts):
    v1 = _create_vendor(client)
    v2 = _create_vendor(client, name="Meg Welder", tax_id="98-7654321")
    run = _create_run(
        client,
        [
            {"vendor_id": v1["id"], "amount": 1200.50, "description": "site work"},
            {"vendor_id": v2["id"], "amount": 800},
        ],
    )
    assert run["status"] == "draft"
    assert run["total_amount"] == 2000.50
    assert {p["vendor_name"] for p in run["payments"]} == {
        "Rick Contractor",
        "Meg Welder",
    }


def test_create_run_rejects_empty_and_negative(client, seed_accounts):
    v = _create_vendor(client)
    r = client.post(
        "/api/contractor-runs", json={"pay_date": "2026-06-05", "payments": []}
    )
    assert r.status_code == 400
    r = client.post(
        "/api/contractor-runs",
        json={
            "pay_date": "2026-06-05",
            "payments": [{"vendor_id": v["id"], "amount": -5}],
        },
    )
    assert r.status_code == 422


def test_create_run_unknown_vendor_404s(client, seed_accounts):
    r = client.post(
        "/api/contractor-runs",
        json={
            "pay_date": "2026-06-05",
            "payments": [{"vendor_id": 999, "amount": 100}],
        },
    )
    assert r.status_code == 404


# --- process ----------------------------------------------------------------


def test_process_posts_balanced_je(client, db_session, seed_accounts):
    v = _create_vendor(client)
    run = _create_run(client, [{"vendor_id": v["id"], "amount": 1500}])
    r = client.post(f"/api/contractor-runs/{run['id']}/process")
    assert r.status_code == 200, r.text
    txn_id = r.json()["transaction_id"]

    from app.models.transactions import TransactionLine

    lines = db_session.query(TransactionLine).filter_by(transaction_id=txn_id).all()
    debits = sum(Decimal(str(line.debit or 0)) for line in lines)
    credits = sum(Decimal(str(line.credit or 0)) for line in lines)
    assert debits == credits == Decimal("1500")


def test_process_is_idempotent(client, seed_accounts):
    v = _create_vendor(client)
    run = _create_run(client, [{"vendor_id": v["id"], "amount": 100}])
    assert client.post(f"/api/contractor-runs/{run['id']}/process").status_code == 200
    assert client.post(f"/api/contractor-runs/{run['id']}/process").status_code == 400


def test_process_respects_closing_date(client, seed_accounts):
    v = _create_vendor(client)
    run = _create_run(client, [{"vendor_id": v["id"], "amount": 100}], "2026-01-15")
    r = client.put("/api/settings", json={"closing_date": "2026-03-31"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/contractor-runs/{run['id']}/process")
    assert r.status_code == 403  # closing-date guard convention
    assert "clos" in r.json()["detail"].lower()


# --- vendor bank + NACHA ----------------------------------------------------


def test_vendor_bank_encrypts_and_supersedes(client, db_session, seed_accounts):
    v = _create_vendor(client)
    r = client.post(
        f"/api/contractor-runs/vendors/{v['id']}/bank",
        json={"routing_number": "021000021", "account_number": "111122223333"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["account_last_four"] == "3333"

    # Raw numbers never stored in clear.
    from app.models.contractor_payments import VendorBankAccount

    row = db_session.query(VendorBankAccount).filter_by(vendor_id=v["id"]).first()
    assert "111122223333" not in (row.account_number_enc or "")
    assert "021000021" not in (row.routing_number_enc or "")

    # Adding a second account deactivates the first.
    r = client.post(
        f"/api/contractor-runs/vendors/{v['id']}/bank",
        json={"routing_number": "021000021", "account_number": "999988887777"},
    )
    assert r.status_code == 201
    accounts = client.get(f"/api/contractor-runs/vendors/{v['id']}/bank").json()
    active = [a for a in accounts if a["is_active"]]
    assert len(active) == 1
    assert active[0]["account_last_four"] == "7777"


def test_vendor_bank_validates_routing(client, seed_accounts):
    v = _create_vendor(client)
    r = client.post(
        f"/api/contractor-runs/vendors/{v['id']}/bank",
        json={"routing_number": "12345", "account_number": "111122223333"},
    )
    assert r.status_code == 400


def test_nacha_credits_contractor_and_skips_unbanked(client, seed_accounts):
    banked = _create_vendor(client, name="Banked LLC")
    unbanked = _create_vendor(client, name="Check Only", tax_id="98-7654321")
    client.post(
        f"/api/contractor-runs/vendors/{banked['id']}/bank",
        json={"routing_number": "021000021", "account_number": "111122223333"},
    )
    run = _create_run(
        client,
        [
            {"vendor_id": banked["id"], "amount": 1000},
            {"vendor_id": unbanked["id"], "amount": 500},
        ],
    )
    # NACHA before processing → 400.
    r = client.post(f"/api/contractor-runs/{run['id']}/nacha", json=ORIGINATING)
    assert r.status_code == 400
    client.post(f"/api/contractor-runs/{run['id']}/process")

    r = client.post(f"/api/contractor-runs/{run['id']}/nacha", json=ORIGINATING)
    assert r.status_code == 200, r.text
    lines = r.text.split("\n")
    assert all(len(line) == 94 for line in lines)
    entries = [line for line in lines if line.startswith("6")]
    # One credit (banked vendor only) + one offsetting company debit.
    assert len(entries) == 2
    credit = entries[0]
    assert "Banked LLC" in credit  # NACHA _alpha keeps case as stored
    assert "0000100000" in credit  # $1,000.00 in cents, 10-wide


# --- 1099 integration -------------------------------------------------------


def test_contractor_payments_feed_1099_totals(client, db_session, seed_accounts):
    v = _create_vendor(client)
    run = _create_run(client, [{"vendor_id": v["id"], "amount": 900}])
    client.post(f"/api/contractor-runs/{run['id']}/process")

    rows = compute_1099_data(db_session, 2026)
    mine = [r for r in rows if r["vendor_id"] == v["id"]][0]
    assert mine["total_paid"] == Decimal("900.00")
    assert mine["reportable"] is True  # over the $600 threshold


def test_draft_runs_do_not_feed_1099(client, db_session, seed_accounts):
    v = _create_vendor(client)
    _create_run(client, [{"vendor_id": v["id"], "amount": 900}])  # never processed
    rows = compute_1099_data(db_session, 2026)
    mine = [r for r in rows if r["vendor_id"] == v["id"]][0]
    assert mine["total_paid"] == Decimal("0.00")


def test_1099_sums_both_payment_paths(client, db_session, seed_accounts):
    """A vendor paid through AP *and* a contractor run reports the sum."""
    v = _create_vendor(client)
    # AP path.
    bill = client.post(
        "/api/bills",
        json={
            "vendor_id": v["id"],
            "date": "2026-03-01",
            "due_date": "2026-03-01",
            "bill_number": "CR-MIX-1",
            "lines": [
                {"description": "work", "quantity": 1, "rate": 400, "line_order": 0}
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
    run = _create_run(client, [{"vendor_id": v["id"], "amount": 300}])
    client.post(f"/api/contractor-runs/{run['id']}/process")

    rows = compute_1099_data(db_session, 2026)
    mine = [r for r in rows if r["vendor_id"] == v["id"]][0]
    assert mine["total_paid"] == Decimal("700.00")
    assert mine["reportable"] is True
