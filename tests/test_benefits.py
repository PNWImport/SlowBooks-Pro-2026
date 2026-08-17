# ============================================================================
# Benefits / ACA / COBRA coverage.
# ----------------------------------------------------------------------------
# Pins enrollment lifecycle (open-enrollment dedupe, end validation),
# months-of-coverage derivation (any-day-of-month rule, partial years),
# self-insured covered-individual listing, 1094 monthly counts, and the
# COBRA notice (102% premium, ended-medical-only guard, audit row).
# ============================================================================


def _create_employee(client, **overrides):
    body = {
        "first_name": "Pat",
        "last_name": "Worker",
        "pay_type": "salary",
        "pay_rate": 60000,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _create_plan(client, **overrides):
    body = {
        "name": "Gold PPO",
        "kind": "medical",
        "carrier_name": "Acme Health",
        "monthly_premium_employee": 150,
        "monthly_premium_employer": 450,
    }
    body.update(overrides)
    r = client.post("/api/benefits/plans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _enroll(client, emp_id, plan_id, start="2026-01-01"):
    r = client.post(
        "/api/benefits/enrollments",
        json={"employee_id": emp_id, "plan_id": plan_id, "coverage_start": start},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_plan_validation(client):
    _create_plan(client)
    assert (
        client.post(
            "/api/benefits/plans", json={"name": "Gold PPO", "kind": "medical"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/benefits/plans", json={"name": "X", "kind": "astral"}
        ).status_code
        == 400
    )


def test_enrollment_lifecycle(client):
    emp = _create_employee(client)
    plan = _create_plan(client)
    enr = _enroll(client, emp["id"], plan["id"])
    assert enr["status"] == "active"

    # Second open enrollment in the same plan rejected.
    r = client.post(
        "/api/benefits/enrollments",
        json={
            "employee_id": emp["id"],
            "plan_id": plan["id"],
            "coverage_start": "2026-02-01",
        },
    )
    assert r.status_code == 400

    # End before start rejected; proper end works; double-end rejected.
    assert (
        client.post(
            f"/api/benefits/enrollments/{enr['id']}/end",
            json={"coverage_end": "2025-12-01"},
        ).status_code
        == 400
    )
    r = client.post(
        f"/api/benefits/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-06-30"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "terminated"
    assert (
        client.post(
            f"/api/benefits/enrollments/{enr['id']}/end",
            json={"coverage_end": "2026-07-31"},
        ).status_code
        == 400
    )


def test_dependents(client):
    emp = _create_employee(client)
    plan = _create_plan(client)
    enr = _enroll(client, emp["id"], plan["id"])
    r = client.post(
        f"/api/benefits/enrollments/{enr['id']}/dependents",
        json={"name": "Kid Worker", "relationship_kind": "child"},
    )
    assert r.status_code == 201
    listed = client.get(f"/api/benefits/enrollments?employee_id={emp['id']}").json()
    assert listed[0]["dependents"][0]["name"] == "Kid Worker"


# --- ACA 1095 ---------------------------------------------------------------


def test_1095_full_year_and_partial(client):
    plan = _create_plan(client)
    full = _create_employee(client, first_name="Full")
    partial = _create_employee(client, first_name="Part")
    _enroll(client, full["id"], plan["id"], "2026-01-01")
    enr = _enroll(client, partial["id"], plan["id"], "2026-03-15")
    client.post(
        f"/api/benefits/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-08-02"},
    )

    data = client.get("/api/tax-forms/1095?year=2026").json()
    assert data["form_count"] == 2
    by_name = {f["name"]: f for f in data["forms"]}
    assert by_name["Full Worker"]["all_12_months"] is True
    # Mar 15 - Aug 2: any day in the month counts -> months 3..8.
    assert by_name["Part Worker"]["months_covered"] == [3, 4, 5, 6, 7, 8]
    # 1094 monthly counts: February has 1 covered employee, April 2.
    assert data["monthly_covered_employee_counts"]["2"] == 1
    assert data["monthly_covered_employee_counts"]["4"] == 2


def test_1095_ignores_non_mec_and_non_medical(client):
    emp = _create_employee(client)
    dental = _create_plan(client, name="Dental", kind="dental")
    nonmec = _create_plan(client, name="Skinny", kind="medical", provides_mec=False)
    _enroll(client, emp["id"], dental["id"])
    _enroll(client, emp["id"], nonmec["id"])
    data = client.get("/api/tax-forms/1095?year=2026").json()
    assert data["form_count"] == 0


def test_1095_self_insured_lists_covered_individuals(client):
    emp = _create_employee(client, first_name="Self")
    plan = _create_plan(client, name="Self-Funded", self_insured=True)
    enr = _enroll(client, emp["id"], plan["id"])
    client.post(
        f"/api/benefits/enrollments/{enr['id']}/dependents",
        json={"name": "Kid Worker", "relationship_kind": "child"},
    )
    data = client.get("/api/tax-forms/1095?year=2026").json()
    form = data["forms"][0]
    assert form["self_insured"] is True
    names = {c["name"] for c in form["covered_individuals"]}
    assert names == {"Self Worker", "Kid Worker"}


# --- COBRA ------------------------------------------------------------------


def test_cobra_notice_requires_ended_medical(client):
    emp = _create_employee(client)
    plan = _create_plan(client)
    enr = _enroll(client, emp["id"], plan["id"])
    # Active enrollment: 400.
    assert (
        client.post(f"/api/benefits/enrollments/{enr['id']}/cobra-notice").status_code
        == 400
    )

    client.post(
        f"/api/benefits/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-06-30"},
    )
    r = client.post(f"/api/benefits/enrollments/{enr['id']}/cobra-notice")
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-"
    audits = client.get("/api/document-audits?doc_type=cobra").json()
    rows = audits if isinstance(audits, list) else audits.get("items", audits)
    assert any(a["doc_key"] == f"enr{enr['id']}" for a in rows)


def test_cobra_notice_rejects_dental(client):
    emp = _create_employee(client)
    plan = _create_plan(client, name="Dental2", kind="dental")
    enr = _enroll(client, emp["id"], plan["id"])
    client.post(
        f"/api/benefits/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-06-30"},
    )
    assert (
        client.post(f"/api/benefits/enrollments/{enr['id']}/cobra-notice").status_code
        == 400
    )
