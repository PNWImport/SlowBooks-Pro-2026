"""Retro wages correct paid rate-derived work, never pending or claimed work."""

import json
from datetime import date
from decimal import Decimal

import pytest

from app.models.payroll import Employee, PayRun, PayRunStatus, PayRunType, PayStub
from tests.test_retro_pay import _create_employee, _run_payroll


def _request(employee_id, **changes):
    return {
        "employee_id": employee_id,
        "new_rate": "25",
        "effective_date": "2026-05-01",
        "pay_date": "2026-05-29",
        **changes,
    }


def test_unpaid_regular_draft_creates_no_retro_arrears(
    client, db_session, seed_accounts
):
    employee = _create_employee(client)
    draft = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-05-01",
            "period_end": "2026-05-14",
            "pay_date": "2026-05-29",
            "stubs": [{"employee_id": employee["id"], "hours": 80}],
        },
    ).json()
    before = db_session.query(PayRun).count()
    preview = client.post(
        "/api/payroll/retro-pay/preview", json=_request(employee["id"])
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["retro_pay_due"] == 0 and preview.json()["periods"] == []
    apply = client.post("/api/payroll/retro-pay/apply", json=_request(employee["id"]))
    assert apply.status_code == 400, apply.text
    db_session.expire_all()
    assert db_session.query(PayRun).count() == before
    assert db_session.get(Employee, employee["id"]).pay_rate == Decimal("20")
    assert db_session.get(PayRun, draft["id"]).status == PayRunStatus.DRAFT


@pytest.mark.parametrize("processed", [False, True])
def test_pending_and_paid_retro_claims_cannot_be_applied_twice(
    client, db_session, seed_accounts, processed
):
    employee = _create_employee(client)
    source = _run_payroll(client, employee["id"], "2026-05-15")
    first = client.post("/api/payroll/retro-pay/apply", json=_request(employee["id"]))
    assert first.status_code == 201, first.text
    run_id = first.json()["pay_run_id"]
    assert first.json()["retro_pay"] == 400
    detail = json.loads(
        db_session.query(PayStub).filter_by(pay_run_id=run_id).one().detail_json
    )
    assert detail["retro_source_run_ids"] == [source["id"]]
    if processed:
        assert client.post(f"/api/payroll/{run_id}/process").status_code == 200
    before = db_session.query(PayRun).count()
    for action in ("preview", "apply"):
        response = client.post(
            f"/api/payroll/retro-pay/{action}", json=_request(employee["id"])
        )
        assert response.status_code == 409, response.text
        assert "already claims" in response.json()["detail"]
    assert db_session.query(PayRun).count() == before
    if not processed:
        assert client.post(f"/api/payroll/{run_id}/cancel").status_code == 200
        reviewed = client.post(
            "/api/payroll/retro-pay/apply", json=_request(employee["id"])
        )
        assert reviewed.status_code == 201, reviewed.text
        assert reviewed.json()["retro_pay"] == 400
        assert (
            client.post(
                f"/api/payroll/{reviewed.json()['pay_run_id']}/process"
            ).status_code
            == 200
        )


def test_disjoint_paid_source_periods_can_have_separate_raises(client, seed_accounts):
    employee = _create_employee(client)
    _run_payroll(client, employee["id"], "2026-05-15")
    first = client.post("/api/payroll/retro-pay/apply", json=_request(employee["id"]))
    assert first.status_code == 201
    assert (
        client.post(f"/api/payroll/{first.json()['pay_run_id']}/process").status_code
        == 200
    )
    _run_payroll(client, employee["id"], "2026-06-15")
    second = client.post(
        "/api/payroll/retro-pay/apply",
        json=_request(
            employee["id"],
            new_rate="30",
            effective_date="2026-06-01",
            pay_date="2026-06-29",
        ),
    )
    assert second.status_code == 201, second.text
    assert second.json()["retro_pay"] == 400


def test_identifiable_legacy_retro_without_sources_refuses_new_claims(
    client, db_session, seed_accounts
):
    employee = _create_employee(client)
    _run_payroll(client, employee["id"], "2026-05-15")
    legacy = PayRun(
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 29),
        pay_date=date(2026, 5, 29),
        status=PayRunStatus.PROCESSED,
        run_type=PayRunType.OFF_CYCLE,
    )
    db_session.add(legacy)
    db_session.flush()
    db_session.add(
        PayStub(
            employee_id=employee["id"],
            pay_run_id=legacy.id,
            gross_pay=400,
            detail_json='{"retro_pay":"400","effective_date":"2026-05-01"}',
        )
    )
    db_session.commit()
    response = client.post(
        "/api/payroll/retro-pay/apply", json=_request(employee["id"])
    )
    assert response.status_code == 409, response.text
    assert "no verified source claims" in response.json()["detail"]


def test_fixed_tips_are_preserved_in_reprice_and_not_paid_a_second_time(
    client, db_session, seed_accounts
):
    employee = _create_employee(client)
    original = _run_payroll(
        client,
        employee["id"],
        "2026-05-15",
        stub={
            "employee_id": employee["id"],
            "hours": 80,
            "reported_tips": "200",
            "paycheck_tips": "100",
        },
    )
    assert original["total_gross"] == 1900
    saved = db_session.get(PayStub, original["stubs"][0]["id"])
    total_tax = (
        saved.federal_tax
        + saved.ss_tax
        + saved.medicare_tax
        + saved.state_tax
        + saved.state_other_employee
        + saved.local_tax
    )
    assert saved.net_pay == Decimal("1900") - total_tax - Decimal("200")
    preview = client.post(
        "/api/payroll/retro-pay/preview", json=_request(employee["id"])
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["periods"][0]["gross_at_new_rate"] == 2300
    assert preview.json()["retro_pay_due"] == 400
    applied = client.post("/api/payroll/retro-pay/apply", json=_request(employee["id"]))
    assert applied.status_code == 201, applied.text
    retro = client.get(f"/api/payroll/{applied.json()['pay_run_id']}").json()["stubs"][
        0
    ]
    assert (
        retro["gross_pay"] == 400
        and retro["reported_tips"] == 0
        and retro["paycheck_tips"] == 0
    )


@pytest.mark.parametrize("new_rate,expected", [("4", 0), ("10", 11)])
def test_recorded_tip_topup_guarantee_is_not_subtracted_from_raise(
    client, seed_accounts, monkeypatch, new_rate, expected
):
    from app import config

    monkeypatch.setattr(config, "MINIMUM_WAGE", "7.25")
    employee = _create_employee(client, pay_rate=2)
    paid = _run_payroll(
        client,
        employee["id"],
        "2026-05-15",
        stub={
            "employee_id": employee["id"],
            "hours": 4,
            "reported_tips": "0",
            "paycheck_tips": "0.01",
        },
    )
    assert paid["total_gross"] == 29
    preview = client.post(
        "/api/payroll/retro-pay/preview",
        json=_request(employee["id"], new_rate=new_rate),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["retro_pay_due"] == expected + (0.01 if expected else 0)


def test_salary_reprice_uses_recorded_frequency_not_current_employee_frequency(
    client, db_session, seed_accounts
):
    from app.models.payroll import PayFrequency

    employee = _create_employee(client, pay_type="salary", pay_rate=52000)
    _run_payroll(client, employee["id"], "2026-05-15")
    db_session.get(Employee, employee["id"]).pay_frequency = PayFrequency.MONTHLY
    db_session.commit()
    preview = client.post(
        "/api/payroll/retro-pay/preview",
        json=_request(employee["id"], new_rate="54600"),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["retro_pay_due"] == 100


@pytest.mark.parametrize(
    "source,current,old_rate,new_rate",
    [("hourly", "salary", "20", "54600"), ("salary", "hourly", "52000", "25")],
)
def test_pay_type_conversion_cannot_reinterpret_new_rate_units(
    client, db_session, seed_accounts, source, current, old_rate, new_rate
):
    from app.models.payroll import PayType

    employee = _create_employee(client, pay_type=source, pay_rate=old_rate)
    paid = _run_payroll(client, employee["id"], "2026-05-15")
    db_session.get(Employee, employee["id"]).pay_type = PayType(current)
    db_session.get(Employee, employee["id"]).pay_rate = Decimal(new_rate)
    db_session.commit()
    for action in ("preview", "apply"):
        response = client.post(
            f"/api/payroll/retro-pay/{action}",
            json=_request(employee["id"], new_rate=new_rate),
        )
        assert response.status_code == 409, response.text
        assert "different rate units" in response.json()["detail"]
    db_session.expire_all()
    assert db_session.query(PayRun).count() == 1
    assert db_session.get(PayRun, paid["id"]).status == PayRunStatus.PROCESSED


def test_explicit_override_is_not_repriced_and_unknown_legacy_basis_is_refused(
    client, db_session, seed_accounts
):
    employee = _create_employee(client)
    run = _run_payroll(
        client,
        employee["id"],
        "2026-05-15",
        stub={"employee_id": employee["id"], "gross_override": "1000"},
    )
    response = client.post(
        "/api/payroll/retro-pay/preview", json=_request(employee["id"])
    )
    assert response.status_code == 200 and response.json()["retro_pay_due"] == 0
    saved = db_session.get(PayStub, run["stubs"][0]["id"])
    detail = json.loads(saved.detail_json)
    detail.pop("_payroll_earnings")
    saved.detail_json = json.dumps(detail)
    db_session.commit()
    response = client.post(
        "/api/payroll/retro-pay/preview", json=_request(employee["id"])
    )
    assert response.status_code == 409, response.text
    assert "unverified" in response.json()["detail"]


def test_legacy_recorded_hours_do_not_prove_rate_derived_earnings(
    client, db_session, seed_accounts
):
    employee = _create_employee(client)
    paid = _run_payroll(client, employee["id"], "2026-05-15")
    stub = db_session.get(PayStub, paid["stubs"][0]["id"])
    detail = json.loads(stub.detail_json)
    detail.pop("_payroll_earnings")
    stub.detail_json = json.dumps(detail)
    assert stub.hours == 80
    db_session.commit()
    response = client.post(
        "/api/payroll/retro-pay/preview", json=_request(employee["id"])
    )
    assert response.status_code == 409, response.text
    assert "unverified" in response.json()["detail"]


@pytest.mark.parametrize(
    "effective,expected", [("2026-05-15", 200), ("2026-05-08", 409)]
)
def test_retro_eligibility_uses_work_period_and_refuses_unallocated_partial_work(
    client, db_session, seed_accounts, effective, expected
):
    employee = _create_employee(client)
    run = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-05-01",
            "period_end": "2026-05-14",
            "pay_date": "2026-05-15",
            "stubs": [{"employee_id": employee["id"], "hours": 80}],
        },
    ).json()
    assert client.post(f"/api/payroll/{run['id']}/process").status_code == 200
    before = db_session.query(PayRun).count()
    response = client.post(
        "/api/payroll/retro-pay/preview",
        json=_request(employee["id"], effective_date=effective),
    )
    assert response.status_code == expected, response.text
    if expected == 200:
        assert (
            response.json()["retro_pay_due"] == 0 and response.json()["periods"] == []
        )
        assert (
            client.post(
                "/api/payroll/retro-pay/apply",
                json=_request(employee["id"], effective_date=effective),
            ).status_code
            == 400
        )
    else:
        assert "partial period" in response.json()["detail"]
        assert (
            client.post(
                "/api/payroll/retro-pay/apply",
                json=_request(employee["id"], effective_date=effective),
            ).status_code
            == 409
        )
    assert db_session.query(PayRun).count() == before


@pytest.mark.parametrize("source_ids", [[], [999999], [True], [0], [1, 1]])
def test_unverified_retro_source_claims_cannot_be_processed(
    client, db_session, seed_accounts, source_ids
):
    employee = _create_employee(client)
    _run_payroll(client, employee["id"], "2026-05-15")
    applied = client.post("/api/payroll/retro-pay/apply", json=_request(employee["id"]))
    assert applied.status_code == 201, applied.text
    stub = (
        db_session.query(PayStub)
        .filter_by(pay_run_id=applied.json()["pay_run_id"])
        .one()
    )
    detail = json.loads(stub.detail_json)
    detail["retro_source_run_ids"] = source_ids
    stub.detail_json = json.dumps(detail)
    db_session.commit()
    response = client.post(f"/api/payroll/{stub.pay_run_id}/process")
    assert response.status_code == 409, response.text
    assert "Retro source claims" in response.json()["detail"]
    db_session.expire_all()
    assert (
        stub.pay_run.status == PayRunStatus.DRAFT
        and stub.pay_run.transaction_id is None
    )


def test_prorated_salary_cannot_be_repriced_as_an_unqualified_full_period(
    client, seed_accounts
):
    employee = _create_employee(client, pay_type="salary", pay_rate=52000)
    run = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-05-01",
            "period_end": "2026-05-14",
            "pay_date": "2026-05-15",
            "stubs": [
                {
                    "employee_id": employee["id"],
                    "old_rate": "26000",
                    "rate_change_date": "2026-05-08",
                }
            ],
        },
    ).json()
    assert client.post(f"/api/payroll/{run['id']}/process").status_code == 200
    response = client.post(
        "/api/payroll/retro-pay/preview",
        json=_request(employee["id"], new_rate="54600"),
    )
    assert response.status_code == 409, response.text
    assert "Prorated salary" in response.json()["detail"]


@pytest.mark.parametrize("action", ["preview", "apply"])
@pytest.mark.parametrize(
    "changes",
    [
        {"new_rate": "NaN"},
        {"new_rate": "Infinity"},
        {"new_rate": "1e99"},
        {"new_rate": "0"},
        {"new_rate": "-1"},
        {"new_rate": "2.999"},
        {"pay_date": "2026-04-30"},
    ],
)
def test_invalid_retro_rate_or_dates_are_422_without_writing(
    client, db_session, changes, action
):
    employee = _create_employee(client)
    before = db_session.query(PayRun).count()
    response = client.post(
        f"/api/payroll/retro-pay/{action}", json=_request(employee["id"], **changes)
    )
    assert response.status_code == 422, response.text
    assert db_session.query(PayRun).count() == before
    db_session.expire_all()
    assert db_session.get(Employee, employee["id"]).pay_rate == Decimal("20")


@pytest.mark.parametrize("current_rate", [20, 30])
def test_apply_never_offsets_arrears_by_clawing_back_another_paid_period(
    client, db_session, seed_accounts, current_rate
):
    employee = _create_employee(client)
    _run_payroll(client, employee["id"], "2026-05-07")
    _run_payroll(client, employee["id"], "2026-05-14")
    record = db_session.get(Employee, employee["id"])
    record.pay_rate = Decimal("30")
    db_session.commit()
    _run_payroll(client, employee["id"], "2026-05-21")
    record.pay_rate = Decimal(current_rate)
    db_session.commit()
    preview = client.post(
        "/api/payroll/retro-pay/preview", json=_request(employee["id"])
    )
    assert preview.status_code == 200, preview.text
    assert [period["difference"] for period in preview.json()["periods"]] == [
        400,
        400,
        -400,
    ]
    before = db_session.query(PayRun).count()
    response = client.post(
        "/api/payroll/retro-pay/apply", json=_request(employee["id"])
    )
    assert response.status_code == 400, response.text
    db_session.expire_all()
    assert db_session.query(PayRun).count() == before
    assert record.pay_rate == Decimal(current_rate)


def test_cancelling_a_retro_draft_takes_back_the_raise_it_staged(
    client, db_session, seed_accounts
):
    """Staging gives the new rate at once; cancelling pays no arrears, so the
    raise goes too — unless the rate has been changed since."""
    employee = _create_employee(client)
    _run_payroll(client, employee["id"], "2026-05-15")
    before = Decimal(str(db_session.get(Employee, employee["id"]).pay_rate))

    staged = client.post("/api/payroll/retro-pay/apply", json=_request(employee["id"]))
    assert staged.status_code == 201, staged.text
    db_session.expire_all()
    assert Decimal(str(db_session.get(Employee, employee["id"]).pay_rate)) == 25

    cancelled = client.post(f"/api/payroll/{staged.json()['pay_run_id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    db_session.expire_all()
    assert Decimal(str(db_session.get(Employee, employee["id"]).pay_rate)) == before

    # A lower corrected rate can now be staged instead of being refused.
    corrected = client.post(
        "/api/payroll/retro-pay/apply", json=_request(employee["id"], new_rate="22")
    )
    assert corrected.status_code == 201, corrected.text


def test_cancelling_a_retro_draft_keeps_a_raise_made_after_it(
    client, db_session, seed_accounts
):
    employee = _create_employee(client)
    _run_payroll(client, employee["id"], "2026-05-15")
    staged = client.post("/api/payroll/retro-pay/apply", json=_request(employee["id"]))
    assert staged.status_code == 201, staged.text
    db_session.get(Employee, employee["id"]).pay_rate = Decimal("31")
    db_session.commit()

    assert (
        client.post(f"/api/payroll/{staged.json()['pay_run_id']}/cancel").status_code
        == 200
    )
    db_session.expire_all()
    assert Decimal(str(db_session.get(Employee, employee["id"]).pay_rate)) == 31
