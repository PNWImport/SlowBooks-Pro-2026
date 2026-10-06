"""Payroll history selection and rejected-run atomicity."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.payroll import PayRun, PayRunStatus, PayRunType, PayStub
from app.routes.payroll.runs import _last_regular_gross
from tests.test_payroll import _create_employee


def test_regular_gross_uses_only_paid_regular_employee_history_through_pay_date(
    client, db_session
):
    employee = _create_employee(client)
    other = _create_employee(client, first_name="Other")
    assert _last_regular_gross(db_session, employee["id"], date(2026, 2, 1)) == 0
    cases = [
        (1, employee["id"], PayRunType.REGULAR, PayRunStatus.PROCESSED, "11.06"),
        (2, employee["id"], PayRunType.REGULAR, PayRunStatus.PROCESSED, "51.06"),
        (3, employee["id"], PayRunType.REGULAR, PayRunStatus.VOID, "99.01"),
        (4, employee["id"], PayRunType.BONUS, PayRunStatus.PROCESSED, "99.02"),
        (5, other["id"], PayRunType.REGULAR, PayRunStatus.PROCESSED, "99.03"),
        (6, employee["id"], PayRunType.REGULAR, PayRunStatus.PROCESSED, "99.04"),
    ]
    for day, employee_id, run_type, status, gross in cases:
        run = PayRun(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 1),
            pay_date=date(2026, 1, day),
            run_type=run_type,
            status=status,
        )
        db_session.add(run)
        db_session.flush()
        db_session.add(
            PayStub(
                pay_run_id=run.id, employee_id=employee_id, gross_pay=Decimal(gross)
            )
        )
    db_session.commit()
    assert _last_regular_gross(db_session, employee["id"], date(2026, 1, 6)) == Decimal(
        "99.04"
    )


def test_aggregate_reference_ignores_unpaid_regular_and_uses_paid_same_day(
    client, db_session
):
    employee = _create_employee(client)
    for status, gross in [
        (PayRunStatus.PROCESSED, "2000"),
        (PayRunStatus.DRAFT, "9999"),
    ]:
        run = PayRun(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 15),
            pay_date=date(2026, 1, 16),
            status=status,
            run_type=PayRunType.REGULAR,
        )
        db_session.add(run)
        db_session.flush()
        db_session.add(
            PayStub(
                employee_id=employee["id"], pay_run_id=run.id, gross_pay=Decimal(gross)
            )
        )
    db_session.commit()
    assert _last_regular_gross(
        db_session, employee["id"], date(2026, 1, 16)
    ) == Decimal("2000")


def test_aggregate_reference_is_snapshot_federal_wages_including_ordinary_fringe(
    client, db_session
):
    import json

    from app.models.benefits import PayStubBenefit
    from tests.test_payroll_fica_ytd import _prior

    employee = _create_employee(client)
    prior = _prior(db_session, employee["id"], "1000", "100")
    prior.pay_run.run_type = PayRunType.REGULAR
    db_session.add(
        PayStubBenefit(
            pay_stub_id=prior.id,
            code="ORDINARY-FRINGE",
            name="Ordinary employer contribution",
            kind="benefit",
            category="posttax",
            calc_method="fixed_amount",
            employer_amount=50,
            rule_json=json.dumps(
                {
                    "employer_taxable": True,
                    "employer_tax_treatment": "fully_taxable",
                    "taxable_employer_amount": "50.00",
                }
            ),
        )
    )
    db_session.commit()
    # $1,000 cash + $50 valued ordinary fringe - $100 qualified deduction.
    assert _last_regular_gross(
        db_session, employee["id"], date(2026, 6, 20)
    ) == Decimal("950")


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"run_type": "invalid"}, 400),
        ({"stubs": [{"employee_id": 999999, "gross_override": "51.06"}]}, 404),
    ],
)
def test_rejected_creation_leaves_no_partial_pay_run(
    client, db_session, payload, status
):
    before = db_session.query(PayRun).count()
    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-01-01",
            "period_end": "2026-01-15",
            "pay_date": "2026-01-16",
            **payload,
        },
    )
    assert response.status_code == status, response.text
    assert db_session.query(PayRun).count() == before
    assert db_session.query(PayStub).count() == 0


def test_void_run_cannot_be_processed(client, db_session):
    run = PayRun(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 15),
        pay_date=date(2026, 1, 16),
        status=PayRunStatus.VOID,
    )
    db_session.add(run)
    db_session.commit()
    response = client.post(f"/api/payroll/{run.id}/process")
    assert response.status_code == 400
    assert "void" in response.json()["detail"].lower()
    db_session.refresh(run)
    assert run.status == PayRunStatus.VOID
    assert run.transaction_id is None


@pytest.fixture
def draft_payroll(client, seed_accounts):
    employee = _create_employee(client)
    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-01-01",
            "period_end": "2026-01-15",
            "pay_date": "2026-01-16",
            "stubs": [{"employee_id": employee["id"], "gross_override": "51.06"}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_failed_job_costing_rolls_back_payroll_journal(
    client, db_session, draft_payroll, monkeypatch
):
    from app.models.transactions import Transaction
    from app.services import job_costing

    before = db_session.query(Transaction).count()

    def reject(db, run):
        assert run.transaction_id is not None
        assert db.query(Transaction).count() == before + 1
        raise ValueError("Payroll burden mapping is incomplete")

    monkeypatch.setattr(job_costing, "distribute_payroll_burden", reject)
    response = client.post(f"/api/payroll/{draft_payroll['id']}/process")
    assert response.status_code == 400, response.text
    assert db_session.query(Transaction).count() == before
    run = db_session.get(PayRun, draft_payroll["id"])
    assert run.status == PayRunStatus.DRAFT
    assert run.transaction_id is None


@pytest.mark.parametrize("missing", [("1000",), ("6110", "6000")])
def test_missing_required_account_leaves_payroll_unprocessed(
    client, db_session, draft_payroll, missing
):
    from app.models.accounts import Account
    from app.models.transactions import Transaction

    db_session.query(Account).filter(Account.account_number.in_(missing)).delete(
        synchronize_session=False
    )
    db_session.commit()
    before = db_session.query(Transaction).count()
    response = client.post(f"/api/payroll/{draft_payroll['id']}/process")
    assert response.status_code == 400, response.text
    assert "Required payroll accounts" in response.json()["detail"]
    run = db_session.get(PayRun, draft_payroll["id"])
    assert run.status == PayRunStatus.DRAFT and run.transaction_id is None
    assert db_session.query(Transaction).count() == before


@pytest.mark.parametrize(
    "detail",
    [
        "{}",
        '{"garnishment:bad": 1}',
        '{"ordinary": 1, "garnishment:bad": 1, "garnishment:tax:x": 1, "garnishment:tax:1": "invalid", "garnishment:tax:2": 0}',
    ],
)
def test_unusable_diagnostic_entries_create_no_remittances(
    client, db_session, draft_payroll, detail
):
    from app.models.deductions import GarnishmentRemittance

    stub = db_session.query(PayStub).filter_by(pay_run_id=draft_payroll["id"]).one()
    assert stub.garnishments == 0
    import json

    # Garbled optional garnishment diagnostics must not destroy the separate
    # verified history that protects reviewed draft tax calculations.
    history = json.loads(stub.detail_json)["_payroll_history"]
    stub.detail_json = json.dumps(json.loads(detail) | {"_payroll_history": history})
    db_session.commit()
    response = client.post(f"/api/payroll/{draft_payroll['id']}/process")
    assert response.status_code == 200, response.text
    assert db_session.query(GarnishmentRemittance).count() == 0
    assert db_session.get(PayRun, draft_payroll["id"]).status == PayRunStatus.PROCESSED


@pytest.mark.parametrize(
    "target,status",
    [("0.00", 400), ("-0.01", 400), ("51.061", 422), ("NaN", 422), ("Infinity", 422)],
)
def test_gross_up_rejects_invalid_target_without_creating_payroll(
    client, db_session, target, status
):
    employee = _create_employee(client)
    response = client.post(
        "/api/payroll/gross-up",
        json={"employee_id": employee["id"], "target_net": target},
    )
    assert response.status_code == status, response.text
    assert db_session.query(PayRun).count() == 0
    assert db_session.query(PayStub).count() == 0


def test_missing_employee_gross_up_returns_not_found(client):
    response = client.post(
        "/api/payroll/gross-up",
        json={"employee_id": 999999, "target_net": "51.06"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Employee not found"


def test_missing_pay_run_cannot_be_processed(client, db_session):
    from app.models.transactions import Transaction

    before = db_session.query(Transaction).count()
    response = client.post("/api/payroll/999999/process")
    assert response.status_code == 404, response.text
    assert db_session.query(Transaction).count() == before


@pytest.mark.parametrize("supplemental", [False, True])
def test_gross_up_quote_preserves_cent_precision_without_posting(
    client, db_session, supplemental
):
    from app.models.transactions import Transaction

    employee = _create_employee(client)
    before = db_session.query(Transaction).count()
    response = client.post(
        "/api/payroll/gross-up",
        json={
            "employee_id": employee["id"],
            "target_net": "51.06",
            "supplemental": supplemental,
        },
    )
    assert response.status_code == 200, response.text
    quote = {
        key: Decimal(str(response.json()[key]))
        for key in ("gross", "net", "withholding")
    }
    assert abs(quote["net"] - Decimal("51.06")) <= Decimal("0.01")
    assert quote["gross"] == quote["net"] + quote["withholding"]
    assert all(value == value.quantize(Decimal("0.01")) for value in quote.values())
    assert db_session.query(Transaction).count() == before
    assert db_session.query(PayRun).count() == 0
    assert db_session.query(PayStub).count() == 0


def test_aggregate_supplemental_run_passes_prior_regular_gross_to_calculator(
    client, db_session, draft_payroll, monkeypatch
):
    from app.routes.payroll import runs

    processed = client.post(f"/api/payroll/{draft_payroll['id']}/process")
    assert processed.status_code == 200, processed.text
    employee_id = draft_payroll["stubs"][0]["employee_id"]
    calculate = runs.calculate_withholdings
    seen = []

    def capture(gross, **kwargs):
        seen.append(kwargs["regular_wages"])
        return calculate(gross, **kwargs)

    monkeypatch.setattr(runs, "calculate_withholdings", capture)
    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-01-16",
            "period_end": "2026-01-31",
            "pay_date": "2026-02-01",
            "run_type": "bonus",
            "stubs": [
                {
                    "employee_id": employee_id,
                    "gross_override": "20.06",
                    "supplemental": True,
                    "supplemental_method": "aggregate",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    assert seen == [Decimal("51.06")]
    assert response.json()["stubs"][0]["gross_pay"] == 20.06
    assert db_session.get(PayRun, draft_payroll["id"]).status == PayRunStatus.PROCESSED
