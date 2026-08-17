# ============================================================================
# Workers' comp premium-report coverage.
# ----------------------------------------------------------------------------
# Pins the per-$100 pricing, (state, class) grouping, supersede-on-re-quote,
# and the missing-rate visibility contract (None premium, named in
# classes_missing_rates — never a silent zero).
# ============================================================================


def _create_employee(client, **overrides):
    body = {
        "first_name": "Pat",
        "last_name": "Worker",
        "pay_type": "hourly",
        "pay_rate": 25,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "TX",
        "wc_class_code": "8810",
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


def test_rate_create_and_supersede(client):
    r = client.post(
        "/api/workers-comp/rates",
        json={"class_code": "8810", "state": "tx", "rate_per_100": 0.35},
    )
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "TX"
    client.post(
        "/api/workers-comp/rates",
        json={"class_code": "8810", "state": "TX", "rate_per_100": 0.40},
    )
    active = [
        row
        for row in client.get("/api/workers-comp/rates").json()
        if row["is_active"] and row["class_code"] == "8810"
    ]
    assert len(active) == 1
    assert active[0]["rate_per_100"] == 0.40

    assert (
        client.post(
            "/api/workers-comp/rates",
            json={"class_code": "X", "state": "TXX", "rate_per_100": 1},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/workers-comp/rates",
            json={"class_code": "X", "state": "TX", "rate_per_100": -1},
        ).status_code
        == 400
    )


def test_premium_report_prices_by_class(client, seed_accounts):
    client.post(
        "/api/workers-comp/rates",
        json={"class_code": "8810", "state": "TX", "rate_per_100": 0.35},
    )
    clerical = _create_employee(client)
    _run(client, clerical["id"])  # 80h * $25 = $2,000 gross

    report = client.get("/api/workers-comp/premium-report?year=2026").json()
    row = report["rows"][0]
    assert (row["state"], row["class_code"]) == ("TX", "8810")
    assert row["wages"] == 2000.00
    assert row["premium"] == 7.00  # 2000/100 * 0.35
    assert report["total_premium"] == 7.00
    assert report["classes_missing_rates"] == []


def test_missing_rate_is_visible_not_zero(client, seed_accounts):
    roofer = _create_employee(client, wc_class_code="5551", first_name="Rae")
    _run(client, roofer["id"])
    report = client.get("/api/workers-comp/premium-report?year=2026").json()
    row = report["rows"][0]
    assert row["premium"] is None
    assert report["classes_missing_rates"] == ["TX:5551"]


def test_unclassified_employees_grouped(client, seed_accounts):
    emp = _create_employee(client, wc_class_code=None)
    _run(client, emp["id"])
    report = client.get("/api/workers-comp/premium-report?year=2026").json()
    assert report["rows"][0]["class_code"] == "UNCLASSIFIED"
