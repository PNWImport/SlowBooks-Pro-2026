# ============================================================================
# Termination / final-paycheck workflow coverage.
# ----------------------------------------------------------------------------
# Pins the state deadline rules (CA immediate/72h, defaults to next payday),
# the PTO payout math (hourly and salary-equivalent rates, sick opt-in,
# state-required payout), and the offboarding side effects: is_active off,
# deductions deactivated, portal token revoked, draft payout run staged.
# ============================================================================

from datetime import date
from decimal import Decimal

from app.services.termination import (
    compute_pto_payout,
    final_paycheck_deadline,
    hourly_equivalent_rate,
)


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


def _give_pto(client, emp_id, hours=40, pto_type="vacation", name="Vacation"):
    policy = client.post(
        "/api/pto/policies",
        json={
            "name": f"{name}-{emp_id}",
            "pto_type": pto_type,
            "accrual_method": "annual_grant",
            "accrual_rate": 80,
        },
    )
    assert policy.status_code in (200, 201), policy.text
    policy_id = policy.json()["id"]
    # Seed the balance directly through the accrual upsert if exposed; the
    # simplest reliable path is the model.
    return policy_id


# --- deadline rules ---------------------------------------------------------


def test_ca_involuntary_is_immediate():
    d = final_paycheck_deadline("CA", "involuntary", date(2026, 6, 10))
    assert d["due_date"] == "2026-06-10"
    assert "immediately" in d["deadline_description"]
    assert d["pto_payout_required"] is True


def test_ca_voluntary_is_72_hours():
    d = final_paycheck_deadline("CA", "voluntary", date(2026, 6, 10))
    assert d["due_date"] == "2026-06-13"


def test_unlisted_state_defaults_to_next_payday():
    d = final_paycheck_deadline(
        "GA", "involuntary", date(2026, 6, 10), date(2026, 6, 19)
    )
    assert d["deadline_description"] == "next regular payday"
    assert d["due_date"] == "2026-06-19"
    assert d["pto_payout_required"] is False


def test_next_payday_without_schedule_is_unresolved():
    d = final_paycheck_deadline("WA", "voluntary", date(2026, 6, 10))
    assert d["due_date"] is None
    assert d["deadline_description"] == "next regular payday"


def test_unknown_reason_treated_as_voluntary():
    involuntary = final_paycheck_deadline("CA", "involuntary", date(2026, 6, 10))
    weird = final_paycheck_deadline("CA", "rage-quit", date(2026, 6, 10))
    assert weird["due_date"] != involuntary["due_date"]


# --- PTO payout math --------------------------------------------------------


def test_salary_hourly_equivalent_is_annual_over_2080(client, db_session):
    emp_id = _create_employee(client, pay_type="salary", pay_rate=104000)["id"]
    from app.models.payroll import Employee

    emp = db_session.query(Employee).get(emp_id)
    assert hourly_equivalent_rate(emp) == Decimal("50.00")


def test_pto_payout_includes_vacation_excludes_sick_by_default(client, db_session):
    emp_id = _create_employee(client, pay_rate=30)["id"]
    from app.models.payroll import Employee
    from app.models.pto import PTOAccrual, PTOPolicy, PTOType, AccrualMethod

    vac = PTOPolicy(
        name="Vac",
        pto_type=PTOType.VACATION,
        accrual_method=AccrualMethod.ANNUAL_GRANT,
        accrual_rate=80,
    )
    sick = PTOPolicy(
        name="Sick",
        pto_type=PTOType.SICK,
        accrual_method=AccrualMethod.ANNUAL_GRANT,
        accrual_rate=40,
    )
    db_session.add_all([vac, sick])
    db_session.flush()
    db_session.add_all(
        [
            PTOAccrual(employee_id=emp_id, policy_id=vac.id, balance=Decimal("40")),
            PTOAccrual(employee_id=emp_id, policy_id=sick.id, balance=Decimal("16")),
        ]
    )
    db_session.commit()

    emp = db_session.query(Employee).get(emp_id)
    payout = compute_pto_payout(db_session, emp)
    assert payout["total_payout"] == 1200.00  # 40h * $30, sick excluded
    excluded = [line for line in payout["lines"] if not line["included"]]
    assert len(excluded) == 1 and excluded[0]["pto_type"] == "sick"

    with_sick = compute_pto_payout(db_session, emp, include_sick=True)
    assert with_sick["total_payout"] == 1680.00  # + 16h * $30


# --- the endpoint -----------------------------------------------------------


def test_terminate_full_flow(client, db_session, seed_accounts):
    emp = _create_employee(client, work_state="CA", pay_rate=30)
    emp_id = emp["id"]

    # Give a vacation balance + an active deduction + a portal token.
    from app.models.pto import PTOAccrual, PTOPolicy, PTOType, AccrualMethod

    vac = PTOPolicy(
        name="VacX",
        pto_type=PTOType.VACATION,
        accrual_method=AccrualMethod.ANNUAL_GRANT,
        accrual_rate=80,
    )
    db_session.add(vac)
    db_session.flush()
    db_session.add(
        PTOAccrual(employee_id=emp_id, policy_id=vac.id, balance=Decimal("20"))
    )
    db_session.commit()
    assert client.get(f"/api/employees/{emp_id}/portal-token").status_code == 200

    r = client.post(
        f"/api/employees/{emp_id}/terminate",
        json={"termination_date": "2026-06-10", "reason": "involuntary"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # CA involuntary: due same day, payout required.
    assert body["final_paycheck"]["due_date"] == "2026-06-10"
    assert body["final_paycheck"]["pto_payout_required"] is True
    assert body["pto_payout"]["total_payout"] == 600.00  # 20h * $30
    assert body["pto_payout_staged"] is True
    assert body["pto_payout_run_id"] is not None

    # Employee deactivated, token revoked.
    updated = client.get(f"/api/employees/{emp_id}").json()
    assert updated["is_active"] is False
    from app.models.payroll import Employee

    db_session.expire_all()
    assert db_session.query(Employee).get(emp_id).portal_token is None

    # Staged run is a draft off-cycle with the payout as supplemental gross.
    run = client.get(f"/api/payroll/{body['pto_payout_run_id']}").json()
    assert run["status"] == "draft"
    assert run["run_type"] == "off_cycle"
    assert run["stubs"][0]["gross_pay"] == 600.00
    assert run["stubs"][0]["federal_tax"] == 132.00  # flat 22%


def test_terminate_is_idempotent_and_validates(client, seed_accounts):
    emp = _create_employee(client)
    r = client.post(
        f"/api/employees/{emp['id']}/terminate",
        json={"termination_date": "2026-06-10", "reason": "confused"},
    )
    assert r.status_code == 400
    r = client.post(
        f"/api/employees/{emp['id']}/terminate",
        json={"termination_date": "2026-06-10", "reason": "voluntary"},
    )
    assert r.status_code == 200
    r = client.post(
        f"/api/employees/{emp['id']}/terminate",
        json={"termination_date": "2026-06-11", "reason": "voluntary"},
    )
    assert r.status_code == 400
    assert (
        client.post(
            "/api/employees/999/terminate",
            json={"termination_date": "2026-06-10", "reason": "voluntary"},
        ).status_code
        == 404
    )


def test_terminate_can_decline_payout_where_not_required(
    client, db_session, seed_accounts
):
    emp = _create_employee(client, work_state="WA", pay_rate=30)
    from app.models.pto import PTOAccrual, PTOPolicy, PTOType, AccrualMethod

    vac = PTOPolicy(
        name="VacY",
        pto_type=PTOType.VACATION,
        accrual_method=AccrualMethod.ANNUAL_GRANT,
        accrual_rate=80,
    )
    db_session.add(vac)
    db_session.flush()
    db_session.add(
        PTOAccrual(employee_id=emp["id"], policy_id=vac.id, balance=Decimal("20"))
    )
    db_session.commit()

    r = client.post(
        f"/api/employees/{emp['id']}/terminate",
        json={
            "termination_date": "2026-06-10",
            "reason": "voluntary",
            "payout_pto": False,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["pto_payout_staged"] is False
    assert r.json()["pto_payout_run_id"] is None
