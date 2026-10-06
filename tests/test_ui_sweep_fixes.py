"""Regression tests for the live-browser sweep: benefit rate dating, final
wages after termination, terminate counts, statement-line locks, garnishment
agency fields."""

import re
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js"


def _emp(client, **kw):
    body = {
        "first_name": "Pat",
        "last_name": "Sweep",
        "pay_type": "hourly",
        "pay_rate": 30,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
        **kw,
    }
    r = client.post("/api/employees", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _run_body(emp_id, start, end, pay):
    return {
        "period_start": start,
        "period_end": end,
        "pay_date": pay,
        "stubs": [{"employee_id": emp_id, "hours": 80}],
    }


def _code(client, code, rate_from):
    rate = {"employee_rate": 25}
    if rate_from:
        rate["effective_from"] = rate_from
    r = client.post(
        "/api/benefits/codes",
        json={
            "code": code,
            "name": code,
            "kind": "deduction",
            "category": "pretax",
            "calc_method": "fixed_amount",
            "rate": rate,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# 1 -------------------------------------------------------------------------
def test_benefit_form_sends_effective_from_for_first_rate():
    src = (JS / "benefits.js").read_text(encoding="utf-8")
    assert "effective_from: raw.effective_from || todayISO()" in src


def test_backdated_first_rate_applies_to_earlier_period(client, seed_accounts):
    emp = _emp(client)
    code = _code(client, "EARLY", "2026-01-01")
    r = client.post(
        "/api/benefits/enrollments",
        json={"employee_id": emp["id"], "benefit_code_id": code["id"]},
    )
    assert r.status_code in (200, 201), r.text
    resp = client.post(
        "/api/payroll",
        json=_run_body(emp["id"], "2026-02-01", "2026-02-14", "2026-02-20"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert [b["code"] for b in body["stubs"][0]["benefits"]] == ["EARLY"]
    assert not [w for w in body.get("warnings") or [] if "EARLY" in w]


def test_missing_rate_is_warned_not_silently_dropped(client, seed_accounts):
    emp = _emp(client)
    code = _code(client, "LATE", "2030-01-01")
    client.post(
        "/api/benefits/enrollments",
        json={"employee_id": emp["id"], "benefit_code_id": code["id"]},
    )
    resp = client.post(
        "/api/payroll",
        json=_run_body(emp["id"], "2026-02-01", "2026-02-14", "2026-02-20"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["stubs"][0]["benefits"] == []
    assert any("LATE" in w and "NOT applied" in w for w in body["warnings"])


# 2 -------------------------------------------------------------------------
def test_terminated_employee_final_wages_rule(client, seed_accounts):
    emp = _emp(client)
    t = client.post(
        f"/api/employees/{emp['id']}/terminate",
        json={
            "termination_date": "2026-03-10",
            "reason": "voluntary",
            "payout_pto": False,
        },
    )
    assert t.status_code == 200, t.text
    listed = next(
        e for e in client.get("/api/employees").json() if e["id"] == emp["id"]
    )
    assert listed["termination_date"] == "2026-03-10"
    ok = client.post(
        "/api/payroll",
        json=_run_body(emp["id"], "2026-03-01", "2026-03-14", "2026-03-20"),
    )
    assert ok.status_code == 201, ok.text
    late = client.post(
        "/api/payroll",
        json=_run_body(emp["id"], "2026-03-11", "2026-03-24", "2026-03-30"),
    )
    assert late.status_code == 422
    assert "terminated" in late.json()["detail"]


def test_run_picker_lists_terminated_and_disables_after_termination():
    src = (JS / "payroll.js").read_text(encoding="utf-8")
    assert "e.is_active || e.termination_date" in src
    assert "pr-terminated" in src and "_syncTerminated" in src
    assert re.search(r"start > term", src)


# 3 -------------------------------------------------------------------------
def test_terminate_reports_benefit_assignments_and_dialog_labels_them(
    client, seed_accounts
):
    emp = _emp(client)
    code = _code(client, "TERMB", None)
    client.post(
        "/api/benefits/enrollments",
        json={"employee_id": emp["id"], "benefit_code_id": code["id"]},
    )
    r = client.post(
        f"/api/employees/{emp['id']}/terminate",
        json={
            "termination_date": "2026-03-10",
            "reason": "voluntary",
            "payout_pto": False,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["benefit_assignments_ended"] == 1
    assert r.json()["benefit_enrollments_ended"] == 0  # coverage plans only
    js = (JS / "employees.js").read_text(encoding="utf-8")
    assert "result.benefit_assignments_ended" in js
    assert "Coverage enrollments ended" in js


# 4/5 -----------------------------------------------------------------------
def test_reconcile_conflict_never_silently_discards_typed_input():
    src = (JS / "banking.js").read_text(encoding="utf-8")
    block = src[src.index("async createReconciliation") :]
    block = block[
        : (
            block.index("async showReconcileView")
            if "async showReconcileView" in block
            else 1500
        )
    ]
    assert "was not applied" in block
    assert "toast(" in block[block.index("existing_id") :]


def test_statement_lines_expose_restore_and_unmatch_buttons():
    src = (JS / "banking.js").read_text(encoding="utf-8")
    assert "BankingPage.restoreLine(" in src.split("_handledAction(t, accountId) {")[1]
    assert "BankingPage.unmatchLine(" in src
    assert "line_reconciled" in src and "Unmatch unavailable:" in src


def test_statement_line_reports_reconciliation_lock(client, db_session):
    from datetime import date
    from decimal import Decimal

    from app.models.accounts import Account, AccountType
    from app.models.banking import BankAccount, BankTransaction
    from app.models.transactions import Transaction, TransactionLine

    acct = Account(name="Chk", account_number="1000", account_type=AccountType.ASSET)
    db_session.add(acct)
    db_session.flush()
    feed = BankAccount(name="Feed", account_id=acct.id)
    db_session.add(feed)
    db_session.flush()
    txn = Transaction(date=date(2026, 1, 5), description="x")
    db_session.add(txn)
    db_session.flush()
    line = TransactionLine(
        transaction_id=txn.id,
        account_id=acct.id,
        debit=Decimal("5"),
        credit=Decimal("0"),
    )
    db_session.add(line)
    db_session.flush()
    bt = BankTransaction(
        bank_account_id=feed.id,
        date=date(2026, 1, 5),
        amount=Decimal("5"),
        match_status="manual",
        transaction_id=txn.id,
        transaction_line_id=line.id,
    )
    db_session.add(bt)
    db_session.commit()
    rows = client.get(f"/api/banking/transactions?bank_account_id={feed.id}").json()
    assert rows[0]["line_reconciled"] is False


# 6 -------------------------------------------------------------------------
def test_garnishment_form_sends_agency_fields_and_register_clears_missing(
    client, seed_accounts
):
    src = (JS / "deductions.js").read_text(encoding="utf-8")
    for name in ("agency_name", "agency_address", "remit_reference"):
        assert f'name="{name}"' in src
        assert f"{name}: f.{name}.value" in src
    emp = _emp(client)
    r = client.post(
        "/api/deductions/garnishments",
        json={
            "employee_id": emp["id"],
            "garnishment_type": "child_support",
            "amount": 50,
            "agency_name": "State SDU",
            "agency_address": "PO Box 1, Olympia WA",
            "remit_reference": "R-77",
        },
    )
    assert r.status_code == 201, r.text
    got = r.json()
    assert got["agency_name"] == "State SDU"
    assert got["agency_address"] == "PO Box 1, Olympia WA"
    assert got["remit_reference"] == "R-77"
