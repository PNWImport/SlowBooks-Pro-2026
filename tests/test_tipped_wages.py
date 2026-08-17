# ============================================================================
# Tipped-wage coverage.
# ----------------------------------------------------------------------------
# Pins the top-up guarantee (cash wages + tips vs the minimum-wage floor),
# the taxable-but-not-payable treatment of reported tips, paycheck tips
# riding the check, the FICA-tip-credit $5.15 pin, and the 8846 endpoint.
# ============================================================================

from decimal import Decimal

from app.services.tips import creditable_tips, tip_credit_topup


def _create_employee(client, **overrides):
    body = {
        "first_name": "Sam",
        "last_name": "Server",
        "pay_type": "hourly",
        "pay_rate": 2.13,  # federal tipped cash wage
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "TX",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, emp_id, stub, pay_date="2026-06-05", process=True):
    r = client.post(
        "/api/payroll",
        json={
            "period_start": pay_date,
            "period_end": pay_date,
            "pay_date": pay_date,
            "stubs": [{"employee_id": emp_id, **stub}],
        },
    )
    assert r.status_code == 201, r.text
    run = r.json()
    if process:
        assert client.post(f"/api/payroll/{run['id']}/process").status_code == 200
    return run


# --- pure math --------------------------------------------------------------


def test_topup_when_tips_fall_short():
    # 80h at $2.13 = 170.40 cash; tips 300; floor 7.25*80 = 580 -> 109.60.
    assert tip_credit_topup(
        Decimal("170.40"), Decimal("300"), Decimal("80"), Decimal("7.25")
    ) == Decimal("109.60")


def test_no_topup_when_tips_cover_the_floor():
    assert tip_credit_topup(
        Decimal("170.40"), Decimal("500"), Decimal("80"), Decimal("7.25")
    ) == Decimal("0.00")


def test_creditable_tips_pin():
    # 5.15*80 = 412 needed; cash 170.40 -> shortfall 241.60; tips 500
    # -> creditable 258.40.
    assert creditable_tips(Decimal("170.40"), Decimal("500"), Decimal("80")) == Decimal(
        "258.40"
    )
    # Cash wages already above the pin: everything creditable.
    assert creditable_tips(Decimal("800"), Decimal("500"), Decimal("80")) == Decimal(
        "500.00"
    )


# --- pay-run integration ----------------------------------------------------


def test_stub_gross_includes_tips_and_topup(client, seed_accounts):
    emp = _create_employee(client)
    run = _run(client, emp["id"], {"hours": 80, "reported_tips": 300}, process=False)
    stub = run["stubs"][0]
    # cash 170.40 + topup 109.60 + tips 300 = 580 (the floor, exactly).
    assert stub["gross_pay"] == 580.00
    assert stub["tip_credit_topup"] == 109.60
    assert stub["reported_tips"] == 300.00


def test_reported_tips_taxed_but_not_paid(client, seed_accounts):
    emp = _create_employee(client)
    run = _run(client, emp["id"], {"hours": 80, "reported_tips": 500}, process=False)
    stub = run["stubs"][0]
    # No topup needed (170.40 + 500 > 580). Gross = 670.40.
    assert stub["gross_pay"] == 670.40
    assert stub["tip_credit_topup"] == 0
    # Net = gross - taxes - reported tips (already in pocket): strictly less
    # than the cash wages, because the check funds tax on the tips too.
    assert stub["net_pay"] < 170.40
    assert stub["net_pay"] > 0


def test_paycheck_tips_ride_the_check(client, seed_accounts):
    emp = _create_employee(client)
    reported = _run(
        client, emp["id"], {"hours": 80, "reported_tips": 500}, process=False
    )["stubs"][0]
    emp2 = _create_employee(client, first_name="Card")
    paycheck = _run(
        client, emp2["id"], {"hours": 80, "paycheck_tips": 500}, process=False
    )["stubs"][0]
    # Same gross and taxes; paycheck tips stay in net (difference = 500).
    assert paycheck["gross_pay"] == reported["gross_pay"]
    assert round(paycheck["net_pay"] - reported["net_pay"], 2) == 500.00


def test_tips_hit_fica_wages(client, seed_accounts):
    emp = _create_employee(client)
    with_tips = _run(
        client, emp["id"], {"hours": 80, "reported_tips": 500}, process=False
    )["stubs"][0]
    emp2 = _create_employee(client, first_name="No", last_name="Tips")
    without = _run(client, emp2["id"], {"hours": 80}, process=False)["stubs"][0]
    assert with_tips["ss_tax"] > without["ss_tax"]


def test_negative_tips_rejected(client, seed_accounts):
    emp = _create_employee(client)
    r = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-06-05",
            "period_end": "2026-06-05",
            "pay_date": "2026-06-05",
            "stubs": [{"employee_id": emp["id"], "hours": 80, "reported_tips": -5}],
        },
    )
    assert r.status_code == 422


# --- 8846 -------------------------------------------------------------------


def test_fica_tip_credit_endpoint(client, seed_accounts):
    emp = _create_employee(client)
    _run(client, emp["id"], {"hours": 80, "reported_tips": 500})
    r = client.get("/api/tax-forms/fica-tip-credit?year=2026")
    assert r.status_code == 200, r.text
    data = r.json()
    # Stub cash wages = gross - tips = 170.40; pin 412 -> creditable 258.40.
    assert data["total_creditable_tips"] == 258.40
    assert data["total_credit"] == round(258.40 * 0.0765, 2)
    assert data["employees"][0]["total_tips"] == 500.00


def test_fica_tip_credit_ignores_untipped(client, seed_accounts):
    emp = _create_employee(client, pay_rate=30)
    _run(client, emp["id"], {"hours": 80})
    data = client.get("/api/tax-forms/fica-tip-credit?year=2026").json()
    assert data["total_credit"] == 0
    assert data["employees"] == []
