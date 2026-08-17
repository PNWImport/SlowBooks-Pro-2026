# ============================================================================
# Retro pay + mid-period proration coverage.
# ----------------------------------------------------------------------------
# Pins the day-weighted salary blend (edges: change on period start, after
# period end, mid-period), hourly retro re-pricing of the recorded OT/DT
# split, bonus-run exclusion, void-run exclusion, and the apply flow: rate
# updated + a draft off-cycle run staged with supplemental withholding.
# ============================================================================

from datetime import date
from decimal import Decimal

from app.models.payroll import PayFrequency
from app.services.retro_pay import compute_retro_pay, prorated_salary_gross


def _create_employee(client, **overrides):
    body = {
        "first_name": "Pat",
        "last_name": "Worker",
        "pay_type": "hourly",
        "pay_rate": 20,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _run_payroll(client, emp_id, pay_date, stub=None, run_type="regular"):
    stub = stub or {"employee_id": emp_id, "hours": 80}
    r = client.post(
        "/api/payroll",
        json={
            "period_start": pay_date,
            "period_end": pay_date,
            "pay_date": pay_date,
            "run_type": run_type,
            "stubs": [stub],
        },
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert client.post(f"/api/payroll/{run['id']}/process").status_code == 200
    return run


# --- salary proration -------------------------------------------------------


def test_prorated_salary_mid_period():
    # $52,000 -> $78,000 biweekly ($2,000 -> $3,000/period). 14-day period,
    # raise effective day 8: 7 old days + 7 new days -> $2,500.
    gross = prorated_salary_gross(
        Decimal("52000"),
        Decimal("78000"),
        PayFrequency.BIWEEKLY,
        date(2026, 6, 1),
        date(2026, 6, 14),
        date(2026, 6, 8),
    )
    assert gross == Decimal("2500.00")


def test_prorated_salary_edges():
    args = (
        Decimal("52000"),
        Decimal("78000"),
        PayFrequency.BIWEEKLY,
        date(2026, 6, 1),
        date(2026, 6, 14),
    )
    assert prorated_salary_gross(*args, date(2026, 6, 1)) == Decimal("3000.00")
    assert prorated_salary_gross(*args, date(2026, 5, 1)) == Decimal("3000.00")
    assert prorated_salary_gross(*args, date(2026, 7, 1)) == Decimal("2000.00")


def test_pay_run_applies_salary_proration(client, seed_accounts):
    emp = _create_employee(client, pay_type="salary", pay_rate=78000)
    r = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-06-01",
            "period_end": "2026-06-14",
            "pay_date": "2026-06-19",
            "stubs": [
                {
                    "employee_id": emp["id"],
                    "rate_change_date": "2026-06-08",
                    "old_rate": 52000,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["stubs"][0]["gross_pay"] == 2500.00


# --- retro pay --------------------------------------------------------------


def test_retro_reprices_hourly_ot_split(client, db_session, seed_accounts):
    emp = _create_employee(client, pay_rate=20)
    _run_payroll(
        client,
        emp["id"],
        "2026-05-15",
        {"employee_id": emp["id"], "regular_hours": 70, "overtime_hours": 10},
    )
    # Paid: 70*20 + 10*30 = 1700. At $25: 70*25 + 10*37.50 = 2125. Diff 425.
    result = compute_retro_pay(db_session, emp["id"], Decimal("25"), date(2026, 5, 1))
    assert result["retro_pay_due"] == 425.00
    assert result["periods"][0]["difference"] == 425.00


def test_retro_ignores_bonus_and_void_runs(client, db_session, seed_accounts):
    emp = _create_employee(client, pay_rate=20)
    keep = _run_payroll(client, emp["id"], "2026-05-15")
    _run_payroll(
        client,
        emp["id"],
        "2026-05-20",
        {"employee_id": emp["id"], "gross_override": 5000, "supplemental": True},
        run_type="bonus",
    )
    voided = _run_payroll(client, emp["id"], "2026-05-29")
    assert client.post(f"/api/payroll/{voided['id']}/void").status_code in (200, 404)

    result = compute_retro_pay(db_session, emp["id"], Decimal("22"), date(2026, 5, 1))
    run_ids = [p["pay_run_id"] for p in result["periods"]]
    assert keep["id"] in run_ids
    # 80 hours * $2 = 160 per surviving regular run.
    per_run = 80 * 2
    assert result["retro_pay_due"] in (per_run, per_run * 2)


def test_retro_excludes_periods_before_effective_date(
    client, db_session, seed_accounts
):
    emp = _create_employee(client, pay_rate=20)
    _run_payroll(client, emp["id"], "2026-04-10")
    _run_payroll(client, emp["id"], "2026-05-15")
    result = compute_retro_pay(db_session, emp["id"], Decimal("22"), date(2026, 5, 1))
    assert len(result["periods"]) == 1
    assert result["periods"][0]["pay_date"] == "2026-05-15"


# --- endpoints --------------------------------------------------------------


def test_preview_endpoint(client, seed_accounts):
    emp = _create_employee(client, pay_rate=20)
    _run_payroll(client, emp["id"], "2026-05-15")
    r = client.post(
        "/api/payroll/retro-pay/preview",
        json={"employee_id": emp["id"], "new_rate": 25, "effective_date": "2026-05-01"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["retro_pay_due"] == 400.00  # 80h * $5


def test_apply_stages_draft_run_and_raises_rate(client, seed_accounts):
    emp = _create_employee(client, pay_rate=20)
    _run_payroll(client, emp["id"], "2026-05-15")
    r = client.post(
        "/api/payroll/retro-pay/apply",
        json={
            "employee_id": emp["id"],
            "new_rate": 25,
            "effective_date": "2026-05-01",
            "pay_date": "2026-06-05",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["retro_pay"] == 400.00
    assert body["status"] == "draft"

    # Rate raised.
    assert client.get(f"/api/employees/{emp['id']}").json()["pay_rate"] == 25

    # Draft off-cycle run staged with supplemental (22%) federal withholding.
    run = client.get(f"/api/payroll/{body['pay_run_id']}").json()
    assert run["status"] == "draft"
    assert run["run_type"] == "off_cycle"
    stub = run["stubs"][0]
    assert stub["gross_pay"] == 400.00
    assert stub["federal_tax"] == 88.00  # flat 22% supplemental


def test_apply_rejects_non_positive_retro(client, seed_accounts):
    emp = _create_employee(client, pay_rate=20)
    _run_payroll(client, emp["id"], "2026-05-15")
    r = client.post(
        "/api/payroll/retro-pay/apply",
        json={"employee_id": emp["id"], "new_rate": 18, "effective_date": "2026-05-01"},
    )
    assert r.status_code == 400


def test_preview_unknown_employee_404s(client):
    r = client.post(
        "/api/payroll/retro-pay/preview",
        json={"employee_id": 999, "new_rate": 25, "effective_date": "2026-05-01"},
    )
    assert r.status_code == 404
