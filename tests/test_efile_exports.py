# ============================================================================
# EFW2 (SSA Pub 42-007) + IRS Pub 1220 e-file export coverage.
# ----------------------------------------------------------------------------
# Structural guarantees the specs demand: fixed record lengths (512 / 750),
# record sequence (RA RE RW* RT RF / T A B* C F), unsigned zero-filled cents,
# CRLF termination — plus the honesty contract: missing SSNs and TINs come
# back as warnings instead of silently emitting an unuploadable file.
# ============================================================================

from decimal import Decimal

import pytest

from app.services.tax_forms.efw2 import _money as efw2_money, generate_efw2
from app.services.tax_forms.irs1220 import generate_1099_fire


def _create_employee(client, **overrides):
    body = {
        "first_name": "Pat",
        "last_name": "Worker",
        "pay_type": "hourly",
        "pay_rate": 25,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
        "address1": "1 Pine St",
        "city": "Seattle",
        "state": "WA",
        "zip": "98101",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _run_payroll(client, emp_id, pay_date="2026-05-15"):
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


def _create_vendor(client, **overrides):
    body = {
        "name": "Rick Contractor",
        "is_1099_vendor": True,
        "tax_id": "12-3456789",
        "w9_on_file": True,
    }
    body.update(overrides)
    r = client.post("/api/vendors", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


_BILL_SEQ = {"n": 0}


def _pay_vendor(client, vendor_id, amount, date="2026-03-01"):
    """Book a bill and pay it so the 1099 total accumulates."""
    _BILL_SEQ["n"] += 1
    bill = client.post(
        "/api/bills",
        json={
            "vendor_id": vendor_id,
            "date": date,
            "due_date": date,
            "bill_number": f"EFILE-{_BILL_SEQ['n']}",
            "lines": [
                {"description": "work", "quantity": 1, "rate": amount, "line_order": 0}
            ],
        },
    )
    assert bill.status_code in (200, 201), bill.text
    bill_id = bill.json()["id"]
    pay = client.post(
        "/api/bill-payments",
        json={
            "vendor_id": vendor_id,
            "date": date,
            "amount": amount,
            "method": "check",
            "allocations": [{"bill_id": bill_id, "amount": amount}],
        },
    )
    assert pay.status_code in (200, 201), pay.text


COMPANY = {
    "name": "Slowbooks Test Co",
    "address": "9 Main St",
    "city": "Olympia",
    "state": "WA",
    "zip": "98501",
    "ein": "91-1234567",
}


# --- shared helpers ---------------------------------------------------------


def test_money_is_unsigned_zero_filled_cents():
    assert efw2_money(Decimal("1234.56")) == "00000123456"
    assert efw2_money(Decimal("0")) == "00000000000"
    assert efw2_money(Decimal("-5")) == "00000000000"  # clamped, never signed


def test_money_overflow_raises():
    with pytest.raises(ValueError):
        efw2_money(Decimal("999999999999"))


# --- EFW2 -------------------------------------------------------------------


def test_efw2_requires_ein(client, db_session):
    with pytest.raises(ValueError, match="EIN"):
        generate_efw2(db_session, 2026, {**COMPANY, "ein": ""})


def test_efw2_structure(client, db_session, seed_accounts):
    a = _create_employee(client, first_name="Ava")
    b = _create_employee(client, first_name="Bo", last_name="Smith")
    _run_payroll(client, a["id"])
    _run_payroll(client, b["id"])

    content, warnings = generate_efw2(db_session, 2026, COMPANY)
    assert content.endswith("\r\n")
    lines = content.rstrip("\r\n").split("\r\n")

    # Record sequence: RA, RE, RW×2, RT, RF — and every record 512 wide.
    assert [ln[:2] for ln in lines] == ["RA", "RE", "RW", "RW", "RT", "RF"]
    assert all(len(ln) == 512 for ln in lines)

    ra, re_rec, rw1, _, rt, rf = lines
    assert ra[2:11] == "911234567"  # EIN, digits only
    assert re_rec[2:6] == "2026"  # tax year
    # SSN zero-filled (app stores last-4 only) and warned about, per employee.
    assert rw1[2:11] == "0" * 9
    assert len([w for w in warnings if "SSN zero-filled" in w]) == 2
    # RT carries the RW count; RF closes the file with the same count.
    assert rt[2:9] == "0000002"
    assert rf[7:16] == "000000002"


def test_efw2_rw_money_matches_w2(client, db_session, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"])
    from app.services.tax_forms.w2_w3 import compute_w2

    w2 = compute_w2(db_session, 2026, emp["id"])
    content, _ = generate_efw2(db_session, 2026, COMPANY)
    rw = [ln for ln in content.split("\r\n") if ln.startswith("RW")][0]
    # Positions 188-198 carry box-1 wages as zero-filled cents.
    expected = str(int(w2["box1_federal_wages"] * 100)).rjust(11, "0")
    assert rw[187:198] == expected


def test_efw2_endpoint(client, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"])
    # No EIN configured in test settings → a clean 400, not a broken file.
    r = client.post("/api/payroll/forms/efw2/2026")
    if r.status_code == 400:
        assert "EIN" in r.json()["detail"]
    else:
        data = r.json()
        assert data["record_length"] == 512
        assert data["content"].startswith("RA")


def test_efw2_endpoint_with_ein(client, seed_accounts, monkeypatch):
    monkeypatch.setattr("app.config.EMPLOYER_EIN", "91-1234567")
    emp = _create_employee(client)
    _run_payroll(client, emp["id"])
    r = client.post("/api/payroll/forms/efw2/2026")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["filename"] == "W2REPORT_2026.txt"
    assert data["content"].startswith("RA")
    assert any("SSN" in w for w in data["warnings"])


# --- IRS Pub 1220 (1099-NEC) ------------------------------------------------


def test_fire_requires_ein(db_session):
    with pytest.raises(ValueError, match="EIN"):
        generate_1099_fire(db_session, 2026, {**COMPANY, "ein": None})


def test_fire_structure_and_totals(client, db_session, seed_accounts):
    v1 = _create_vendor(client, name="Rick Contractor")
    v2 = _create_vendor(client, name="Meg Welder", tax_id="98-7654321")
    _pay_vendor(client, v1["id"], 1500)
    _pay_vendor(client, v2["id"], 700)

    content, warnings = generate_1099_fire(db_session, 2026, COMPANY)
    lines = content.rstrip("\r\n").split("\r\n")
    assert [ln[0] for ln in lines] == ["T", "A", "B", "B", "C", "F"]
    assert all(len(ln) == 750 for ln in lines)

    t, a, b1, b2, c, f = lines
    assert t[1:5] == "2026"
    assert a[25:27] == "NE"  # return type 1099-NEC
    # Payment Amount 1 (positions 55-66) carries the NEC total in cents.
    amounts = sorted([b1[54:66], b2[54:66]])
    assert amounts == ["000000070000", "000000150000"]
    # C record: payee count + control total 2,200.00.
    assert c[1:9] == "00000002"
    assert c[15:33] == "000000000000220000"
    # No TCC configured → warned.
    assert any("Transmitter Control Code" in w for w in warnings)


def test_fire_skips_vendor_without_tin_and_warns(client, db_session, seed_accounts):
    good = _create_vendor(client, name="Has Tin")
    bad = _create_vendor(client, name="No Tin", tax_id=None)
    _pay_vendor(client, good["id"], 800)
    _pay_vendor(client, bad["id"], 900)

    content, warnings = generate_1099_fire(db_session, 2026, COMPANY)
    lines = content.rstrip("\r\n").split("\r\n")
    assert [ln[0] for ln in lines].count("B") == 1
    assert any("No Tin" in w and "skipped" in w for w in warnings)


def test_fire_below_threshold_not_emitted(client, db_session, seed_accounts):
    v = _create_vendor(client)
    _pay_vendor(client, v["id"], 400)  # under $600
    content, _ = generate_1099_fire(db_session, 2026, COMPANY)
    lines = content.rstrip("\r\n").split("\r\n")
    assert [ln[0] for ln in lines] == ["T", "A", "C", "F"]


def test_fire_endpoint(client, seed_accounts, monkeypatch):
    monkeypatch.setattr("app.config.EMPLOYER_EIN", "91-1234567")
    v = _create_vendor(client)
    _pay_vendor(client, v["id"], 2000)
    r = client.get("/api/tax-forms/1099/fire?year=2026")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["filename"] == "IRS1099NEC_2026.txt"
    assert data["record_length"] == 750
    assert data["content"].startswith("T")
