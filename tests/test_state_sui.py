# ============================================================================
# Quarterly SUI wage-report coverage — compute_sui + the new endpoints.
# ----------------------------------------------------------------------------
# The aggregation service predates this file (it shipped as scaffolding with
# the tier-3 tax forms); the JSON + PDF endpoints are new. These tests cover
# both: quarter bounding, per-employee accumulation, the state filter,
# processed-runs-only, the JSON serialization, and the PDF + audit row.
# ============================================================================

from decimal import Decimal

import pytest

from app.services.tax_forms.state_sui import _quarter_bounds, compute_sui


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


def _run_payroll(client, emp_id, pay_date, hours=80, process=True):
    r = client.post(
        "/api/payroll",
        json={
            "period_start": pay_date,
            "period_end": pay_date,
            "pay_date": pay_date,
            "stubs": [{"employee_id": emp_id, "hours": hours}],
        },
    )
    assert r.status_code == 201, r.text
    run = r.json()
    if process:
        pr = client.post(f"/api/payroll/{run['id']}/process")
        assert pr.status_code == 200, pr.text
    return run


# --- quarter bounds ---------------------------------------------------------


@pytest.mark.parametrize(
    "quarter,start,end",
    [
        (1, "2026-01-01", "2026-03-31"),
        (2, "2026-04-01", "2026-06-30"),
        (3, "2026-07-01", "2026-09-30"),
        (4, "2026-10-01", "2026-12-31"),
    ],
)
def test_quarter_bounds(quarter, start, end):
    s, e = _quarter_bounds(2026, quarter)
    assert (str(s), str(e)) == (start, end)


def test_quarter_bounds_rejects_bad_quarter():
    with pytest.raises(ValueError):
        _quarter_bounds(2026, 5)


# --- aggregation ------------------------------------------------------------


def test_sui_aggregates_processed_stubs(client, db_session, seed_accounts):
    emp = _create_employee(client, first_name="Ava")
    run = _run_payroll(client, emp["id"], "2026-05-15")
    data = compute_sui(db_session, 2026, 2)
    assert data["num_employees"] == 1
    assert data["num_stubs"] == 1
    stub = run["stubs"][0]
    assert data["total_wages"] == Decimal(str(stub["gross_pay"]))
    assert data["total_suta_tax"] == Decimal(str(stub["suta_tax"]))
    row = data["employees"][0]
    assert row["name"] == "Ava Worker"
    assert row["work_state"] == "WA"
    # Under the wage base, the whole gross is SUI-taxable.
    assert row["suta_taxable_wages"] == Decimal(str(stub["gross_pay"]))


def test_sui_excludes_draft_runs(client, db_session, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-05-15", process=False)
    data = compute_sui(db_session, 2026, 2)
    assert data["num_stubs"] == 0
    assert data["total_wages"] == 0


def test_sui_respects_quarter_boundaries(client, db_session, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-03-31")  # Q1, last day
    _run_payroll(client, emp["id"], "2026-04-01")  # Q2, first day
    q1 = compute_sui(db_session, 2026, 1)
    q2 = compute_sui(db_session, 2026, 2)
    assert q1["num_stubs"] == 1
    assert q2["num_stubs"] == 1


def test_sui_state_filter(client, db_session, seed_accounts):
    wa = _create_employee(client, first_name="Wa", work_state="WA")
    tx = _create_employee(client, first_name="Tex", work_state="TX", state="TX")
    _run_payroll(client, wa["id"], "2026-05-01")
    _run_payroll(client, tx["id"], "2026-05-01")

    both = compute_sui(db_session, 2026, 2)
    assert both["num_employees"] == 2

    wa_only = compute_sui(db_session, 2026, 2, "WA")
    assert wa_only["num_employees"] == 1
    assert wa_only["employees"][0]["name"] == "Wa Worker"
    assert wa_only["state"] == "WA"


def test_sui_accumulates_multiple_runs_per_employee(client, db_session, seed_accounts):
    emp = _create_employee(client)
    r1 = _run_payroll(client, emp["id"], "2026-04-10")
    r2 = _run_payroll(client, emp["id"], "2026-04-24")
    data = compute_sui(db_session, 2026, 2)
    assert data["num_employees"] == 1
    assert data["num_stubs"] == 2
    expected = Decimal(str(r1["stubs"][0]["gross_pay"])) + Decimal(
        str(r2["stubs"][0]["gross_pay"])
    )
    assert data["total_wages"] == expected


# --- endpoints --------------------------------------------------------------


def test_sui_json_endpoint(client, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-05-15")
    r = client.post("/api/payroll/forms/sui/2026/2")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["year"] == 2026
    assert data["quarter"] == 2
    assert data["num_employees"] == 1
    # Decimals serialize as strings, like the other form endpoints.
    assert isinstance(data["total_wages"], str)
    assert Decimal(data["total_wages"]) > 0
    assert data["employees"][0]["name"] == "Pat Worker"


def test_sui_json_endpoint_state_filter_uppercases(client, seed_accounts):
    emp = _create_employee(client, work_state="TX", state="TX")
    _run_payroll(client, emp["id"], "2026-05-15")
    r = client.post("/api/payroll/forms/sui/2026/2?state=tx")
    assert r.status_code == 200
    assert r.json()["state"] == "TX"
    assert r.json()["num_employees"] == 1


def test_sui_endpoint_rejects_bad_quarter(client):
    assert client.post("/api/payroll/forms/sui/2026/5").status_code == 400
    assert client.post("/api/payroll/forms/sui/2026/5/pdf").status_code == 400


def test_sui_pdf_endpoint_renders_and_audits(client, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-05-15")
    r = client.post("/api/payroll/forms/sui/2026/2/pdf?state=WA")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"

    # The render wrote an audit row keyed to the year/quarter/state.
    audits = client.get("/api/document-audits?doc_type=sui").json()
    rows = audits if isinstance(audits, list) else audits.get("items", audits)
    assert any(a["doc_key"] == "yr2026-q2-WA" for a in rows)


def test_sui_pdf_without_state_covers_all(client, seed_accounts):
    emp = _create_employee(client)
    _run_payroll(client, emp["id"], "2026-05-15")
    r = client.post("/api/payroll/forms/sui/2026/2/pdf")
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"
