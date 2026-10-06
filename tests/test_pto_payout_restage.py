"""A PTO payout blocked by the final paycheck can be staged again.

Terminate stages the payout dated on the termination date. The usual order
is then to pay the final regular check, dated after it — and a draft may not
predate a check already paid in the same year (it would change that check's
tax history). The payout was stuck: it could not be processed, and Terminate
cannot be run twice. Cancelling it and staging it again is the way out, and
processing a payout does not use up the PTO balance, so staging must refuse
once one has been paid.
"""

from decimal import Decimal

from app.models.payroll import PayRun, PayRunStatus, PayStub
from tests.test_termination import _create_employee


def _terminated_with_pto(client, db_session, hours="20"):
    from app.models.pto import AccrualMethod, PTOAccrual, PTOPolicy, PTOType

    emp = _create_employee(client, work_state="CA", pay_rate=30)
    policy = PTOPolicy(
        name=f"Vac-{emp['id']}",
        pto_type=PTOType.VACATION,
        accrual_method=AccrualMethod.ANNUAL_GRANT,
        accrual_rate=80,
    )
    db_session.add(policy)
    db_session.flush()
    db_session.add(
        PTOAccrual(employee_id=emp["id"], policy_id=policy.id, balance=Decimal(hours))
    )
    db_session.commit()
    r = client.post(
        f"/api/employees/{emp['id']}/terminate",
        json={"termination_date": "2026-06-10", "reason": "involuntary"},
    )
    assert r.status_code == 200, r.text
    return emp, r.json()


def _final_check(client, emp_id):
    r = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-06-01",
            "period_end": "2026-06-10",
            "pay_date": "2026-06-12",
            "stubs": [{"employee_id": emp_id, "hours": 80}],
        },
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert client.post(f"/api/payroll/{run['id']}/process").status_code == 200
    return run


def test_a_payout_blocked_by_the_final_check_can_be_staged_again_and_paid(
    client, db_session, seed_accounts
):
    emp, terminated = _terminated_with_pto(client, db_session)
    blocked = terminated["pto_payout_run_id"]
    assert blocked

    _final_check(client, emp["id"])  # paid first, dated after the termination

    held = client.post(f"/api/payroll/{blocked}/process")
    assert held.status_code == 409, held.text
    assert "PTO payout" in held.json()["detail"]  # and it says how to recover

    # while that draft still exists, a second one is refused
    twice = client.post(f"/api/employees/{emp['id']}/pto-payout", json={})
    assert twice.status_code == 409 and "already staged" in twice.json()["detail"]

    assert client.post(f"/api/payroll/{blocked}/cancel").status_code == 200

    staged = client.post(f"/api/employees/{emp['id']}/pto-payout", json={})
    assert staged.status_code == 201, staged.text
    assert staged.json()["pay_date"] == "2026-06-12"  # on or after the paid check
    assert staged.json()["pto_payout"]["total_payout"] == 600.0
    new_id = staged.json()["pay_run_id"]
    stub = db_session.query(PayStub).filter_by(pay_run_id=new_id).one()
    assert Decimal(str(stub.gross_pay)) == Decimal("600")
    assert "pto_payout" in stub.detail_json

    assert client.post(f"/api/payroll/{new_id}/process").status_code == 200
    db_session.expire_all()
    assert db_session.get(PayRun, new_id).status == PayRunStatus.PROCESSED

    # paid: staging again would pay the same time twice
    again = client.post(f"/api/employees/{emp['id']}/pto-payout", json={})
    assert again.status_code == 409 and "already paid" in again.json()["detail"]


def test_restaging_needs_a_termination_and_something_to_pay(
    client, db_session, seed_accounts
):
    active = _create_employee(client)
    r = client.post(f"/api/employees/{active['id']}/pto-payout", json={})
    assert r.status_code == 400 and "Terminate" in r.json()["detail"]

    gone = _create_employee(client, first_name="Gone")
    client.post(
        f"/api/employees/{gone['id']}/terminate",
        json={"termination_date": "2026-06-10", "reason": "voluntary"},
    )
    nothing = client.post(f"/api/employees/{gone['id']}/pto-payout", json={})
    assert nothing.status_code == 400 and "no accrued PTO" in nothing.json()["detail"]


def test_a_payout_cannot_be_dated_before_the_termination_or_a_paid_check(
    client, db_session, seed_accounts
):
    emp, terminated = _terminated_with_pto(client, db_session)
    _final_check(client, emp["id"])
    client.post(f"/api/payroll/{terminated['pto_payout_run_id']}/cancel")

    before = client.post(
        f"/api/employees/{emp['id']}/pto-payout", json={"pay_date": "2026-06-01"}
    )
    assert before.status_code == 422, before.text

    predates_paid = client.post(
        f"/api/employees/{emp['id']}/pto-payout", json={"pay_date": "2026-06-11"}
    )
    assert predates_paid.status_code == 409, predates_paid.text
    assert "on or after" in predates_paid.json()["detail"]
