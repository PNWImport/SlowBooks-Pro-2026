"""Reviewed payroll drafts must not reuse a paid check's annual wage allowance."""

import json
from datetime import date
from decimal import Decimal

import pytest

from app.models.payroll import PayRun, PayRunStatus, PayStub
from app.models.transactions import Transaction
from tests.test_payroll_fica_ytd import _employee, _prior


def _loan(db, employee_id):
    from app.models.benefits import BenefitCode, BenefitRate, EmployeeBenefit

    code = BenefitCode(
        code="LOAN-STAGED",
        name="Loan",
        kind="both",
        category="posttax",
        calc_method="fixed_amount",
        employer_calc_method="fixed_amount",
        tracks_balance=True,
    )
    db.add(code)
    db.flush()
    db.add(
        BenefitRate(
            benefit_code_id=code.id,
            effective_from=date(2026, 1, 1),
            employee_rate=100,
            employer_rate=50,
        )
    )
    assignment = EmployeeBenefit(
        employee_id=employee_id, benefit_code_id=code.id, balance_remaining=250
    )
    db.add(assignment)
    db.commit()
    return code, assignment


def _draft(client, employee_id, paid="2026-06-20", gross="1000", **stub_options):
    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-06-01",
            "period_end": "2026-06-14",
            "pay_date": paid,
            "stubs": [
                {"employee_id": employee_id, "gross_override": gross, **stub_options}
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("second_date", ["2026-06-20", "2026-06-27"])
@pytest.mark.parametrize(
    "prior_gross,field,saved,fresh",
    [
        ("184000", "ss_tax", "31.00", "0.00"),
        ("199500", "medicare_tax", "19.00", "23.50"),
        ("6500", "futa_tax", "3.00", "0.00"),
    ],
)
def test_staged_check_refuses_changed_paid_history_without_rewriting_work(
    client, db_session, seed_accounts, second_date, prior_gross, field, saved, fresh
):
    employee = _employee(client, rate=12.5)
    prior = _prior(db_session, employee["id"], prior_gross, "0")
    first = _draft(client, employee["id"])
    second = _draft(client, employee["id"], second_date)
    assert Decimal(str(first["stubs"][0][field])) == Decimal(saved)
    assert Decimal(str(second["stubs"][0][field])) == Decimal(saved)
    assert client.post(f"/api/payroll/{first['id']}/process").status_code == 200
    before = db_session.query(Transaction).count()
    response = client.post(f"/api/payroll/{second['id']}/process")
    assert response.status_code == 409, response.text
    assert "paid payroll history" in response.json()["detail"].lower()
    db_session.expire_all()
    held = db_session.get(PayRun, second["id"])
    assert held.status == PayRunStatus.DRAFT and held.transaction_id is None
    assert getattr(held.stubs[0], field) == Decimal(saved)
    assert db_session.query(Transaction).count() == before
    assert db_session.get(PayStub, prior.id).gross_pay == Decimal(prior_gross)
    assert db_session.get(PayRun, first["id"]).status == PayRunStatus.PROCESSED
    assert getattr(db_session.get(PayRun, first["id"]).stubs[0], field) == Decimal(
        saved
    )
    # A newly calculated check uses the paid history. The held draft itself
    # is preserved for explicit review; it is never silently rewritten.
    reviewed = _draft(client, employee["id"], second_date)
    assert Decimal(str(reviewed["stubs"][0][field])) == Decimal(fresh)


def test_earlier_pay_date_cannot_change_a_later_processed_checks_cap_context(
    client, db_session, seed_accounts
):
    employee = _employee(client, rate=12.5)
    _prior(db_session, employee["id"], "184000", "0")
    earlier = _draft(client, employee["id"], "2026-06-20")
    later = _draft(client, employee["id"], "2026-06-27")
    assert client.post(f"/api/payroll/{later['id']}/process").status_code == 200
    response = client.post(f"/api/payroll/{earlier['id']}/process")
    assert response.status_code == 409, response.text
    assert "later pay date" in response.json()["detail"].lower()
    db_session.expire_all()
    assert db_session.get(PayRun, later["id"]).stubs[0].ss_tax == Decimal("31.00")
    assert db_session.get(PayRun, earlier["id"]).status == PayRunStatus.DRAFT


def test_other_employee_and_other_year_do_not_invalidate_reviewed_draft(
    client, db_session, seed_accounts
):
    employee = _employee(client, rate=12.5)
    other = _employee(client, rate=12.5)
    draft = _draft(client, employee["id"])
    other_run = _draft(client, other["id"])
    assert client.post(f"/api/payroll/{other_run['id']}/process").status_code == 200
    _prior(db_session, employee["id"], "184500", "0", paid=date(2025, 12, 31))
    response = client.post(f"/api/payroll/{draft['id']}/process")
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("detail", [None, "invalid json", "{}"])
def test_unverified_legacy_or_corrupt_draft_is_held_without_posting(
    client, db_session, seed_accounts, detail
):
    employee = _employee(client, rate=12.5)
    run = _draft(client, employee["id"])
    stub = db_session.get(PayStub, run["stubs"][0]["id"])
    stub.detail_json = detail
    db_session.commit()
    before = db_session.query(Transaction).count()
    response = client.post(f"/api/payroll/{run['id']}/process")
    assert response.status_code == 409, response.text
    assert "review" in response.json()["detail"].lower()
    db_session.expire_all()
    assert db_session.get(PayRun, run["id"]).status == PayRunStatus.DRAFT
    assert db_session.query(Transaction).count() == before


def test_duplicate_employee_stubs_are_rejected_before_reserving_any_work(
    client, db_session, seed_accounts
):
    employee = _employee(client, rate=12.5)
    before = db_session.query(PayRun).count()
    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-06-01",
            "period_end": "2026-06-14",
            "pay_date": "2026-06-20",
            "stubs": [
                {"employee_id": employee["id"], "gross_override": "1000"},
                {"employee_id": employee["id"], "gross_override": "1000"},
            ],
        },
    )
    assert response.status_code == 422, response.text
    assert "one stub" in response.json()["detail"].lower()
    assert db_session.query(PayRun).count() == before


def test_history_metadata_is_not_a_paystub_deduction(client, seed_accounts):
    from app.services.paystub_pdf import _deduction_items

    employee = _employee(client, rate=12.5)
    draft = _draft(client, employee["id"])
    stub = PayStub(
        **{k: v for k, v in draft["stubs"][0].items() if k != "employee_name"}
    )
    stub.detail_json = json.dumps(
        {"_payroll_history": {"version": 1}, "social_security": "62"}
    )
    assert [key for key, _, _ in _deduction_items(stub)] == ["social_security"]


def test_cancel_stale_draft_refunds_only_its_original_reservations_and_allows_review(
    client, db_session, seed_accounts
):
    from app.models.benefits import BenefitYTD

    employee = _employee(client, rate=12.5)
    _prior(db_session, employee["id"], "184000", "0")
    code, assignment = _loan(db_session, employee["id"])
    first = _draft(client, employee["id"])
    second = _draft(client, employee["id"])
    assert client.post(f"/api/payroll/{first['id']}/process").status_code == 200
    assert client.post(f"/api/payroll/{second['id']}/process").status_code == 409
    db_session.expire_all()
    assert assignment.balance_remaining == Decimal("50")
    ytd = db_session.query(BenefitYTD).filter_by(benefit_code_id=code.id).one()
    assert (ytd.employee_amount, ytd.employer_amount) == (
        Decimal("200"),
        Decimal("100"),
    )
    # Rule edits must not redirect the refund or lose the original reservation.
    code.tracks_balance = False
    assignment.is_active = False
    db_session.commit()
    before = db_session.query(Transaction).count()
    response = client.post(f"/api/payroll/{second['id']}/cancel")
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert assignment.balance_remaining == Decimal("150")
    assert (ytd.employee_amount, ytd.employer_amount) == (Decimal("100"), Decimal("50"))
    cancelled = db_session.get(PayRun, second["id"])
    assert cancelled.status == PayRunStatus.VOID and cancelled.transaction_id is None
    assert cancelled.stubs[0].ss_tax == Decimal("31")
    assert cancelled.stubs[0].benefits[0].employee_amount == Decimal("100")
    assert db_session.query(Transaction).count() == before
    repeated = client.post(f"/api/payroll/{second['id']}/cancel")
    assert repeated.status_code == 409
    db_session.expire_all()
    assert assignment.balance_remaining == Decimal("150")
    reviewed = _draft(client, employee["id"])
    assert Decimal(str(reviewed["stubs"][0]["ss_tax"])) == Decimal("0")
    assert client.post(f"/api/payroll/{reviewed['id']}/process").status_code == 200


def test_cancellation_releases_only_time_entries_owned_by_that_draft(
    client, db_session, seed_accounts
):
    from app.models.time_entries import TimeEntry, TimeEntryStatus

    employee = _employee(client, rate=125)
    entry = TimeEntry(
        employee_id=employee["id"],
        date=date(2026, 6, 8),
        hours_regular=8,
        status=TimeEntryStatus.APPROVED,
    )
    db_session.add(entry)
    db_session.commit()
    payload = {
        "period_start": "2026-06-01",
        "period_end": "2026-06-14",
        "pay_date": "2026-06-20",
        "stubs": [{"employee_id": employee["id"], "use_time_entries": True}],
    }
    response = client.post("/api/payroll", json=payload)
    assert response.status_code == 201, response.text
    run = response.json()
    unrelated = _draft(client, employee["id"], "2026-06-27")
    other_entry = TimeEntry(
        employee_id=employee["id"],
        date=date(2026, 6, 9),
        hours_regular=8,
        status=TimeEntryStatus.APPROVED,
        pay_run_id=unrelated["id"],
    )
    db_session.add(other_entry)
    db_session.commit()
    cancelled = client.post(f"/api/payroll/{run['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["released_time_entries"] == 1
    db_session.expire_all()
    assert entry.pay_run_id is None and entry.status == TimeEntryStatus.APPROVED
    assert other_entry.pay_run_id == unrelated["id"]
    restaged = client.post("/api/payroll", json=payload)
    assert restaged.status_code == 201, restaged.text
    assert restaged.json()["stubs"][0]["gross_pay"] == 1000
    db_session.expire_all()
    assert entry.pay_run_id == restaged.json()["id"]


@pytest.mark.parametrize(
    "corrupt", ["legacy", "bad_amount", "missing_loan", "short_ytd"]
)
def test_cancellation_refuses_untrustworthy_reservations_atomically(
    client, db_session, seed_accounts, corrupt
):
    from app.models.benefits import BenefitYTD

    employee = _employee(client, rate=12.5)
    code, assignment = _loan(db_session, employee["id"])
    run = _draft(client, employee["id"])
    stub = db_session.get(PayStub, run["stubs"][0]["id"])
    snapshot = stub.benefits[0]
    rule = json.loads(snapshot.rule_json)
    if corrupt == "legacy":
        rule.pop("draft_reservation", None)
    elif corrupt == "bad_amount":
        rule["draft_reservation"]["balance_reserved"] = "NaN"
    elif corrupt == "missing_loan":
        db_session.delete(assignment)
    else:
        db_session.query(BenefitYTD).filter_by(
            benefit_code_id=code.id
        ).one().employee_amount = 0
    snapshot.rule_json = json.dumps(rule)
    db_session.commit()
    before_ytd = db_session.query(BenefitYTD).filter_by(benefit_code_id=code.id).one()
    before = (before_ytd.employee_amount, before_ytd.employer_amount)
    response = client.post(f"/api/payroll/{run['id']}/cancel")
    assert response.status_code == 409, response.text
    db_session.expire_all()
    assert db_session.get(PayRun, run["id"]).status == PayRunStatus.DRAFT
    assert (before_ytd.employee_amount, before_ytd.employer_amount) == before
    if corrupt != "missing_loan":
        assert assignment.balance_remaining == Decimal("150")


def test_paid_run_cannot_be_cancelled_and_legacy_no_benefit_draft_can(
    client, db_session, seed_accounts
):
    employee = _employee(client, rate=12.5)
    paid = _draft(client, employee["id"])
    assert client.post(f"/api/payroll/{paid['id']}/process").status_code == 200
    before = db_session.query(Transaction).count()
    assert client.post(f"/api/payroll/{paid['id']}/cancel").status_code == 409
    db_session.expire_all()
    assert db_session.get(PayRun, paid["id"]).status == PayRunStatus.PROCESSED
    assert db_session.query(Transaction).count() == before
    legacy = _draft(client, employee["id"])
    db_session.get(PayStub, legacy["stubs"][0]["id"]).detail_json = None
    db_session.commit()
    assert client.post(f"/api/payroll/{legacy['id']}/cancel").status_code == 200


def test_prior_year_regular_reference_change_requires_review(
    client, db_session, seed_accounts
):
    from app.models.payroll import PayRunType

    employee = _employee(client, rate=12.5)
    draft = _draft(
        client, employee["id"], supplemental=True, supplemental_method="aggregate"
    )
    previous = PayRun(
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 15),
        pay_date=date(2025, 12, 20),
        status=PayRunStatus.PROCESSED,
        run_type=PayRunType.REGULAR,
    )
    db_session.add(previous)
    db_session.flush()
    db_session.add(
        PayStub(
            employee_id=employee["id"],
            pay_run_id=previous.id,
            gross_pay=Decimal("2000"),
        )
    )
    db_session.commit()
    response = client.post(f"/api/payroll/{draft['id']}/process")
    assert response.status_code == 409, response.text
    assert "paid payroll history" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    "treatment,amount",
    [
        (None, "50"),
        ("fully_taxable", None),
        ("fully_taxable", "49.99"),
        ("fully_taxable", "NaN"),
    ],
)
def test_snapshot_with_unverified_taxable_fringe_cannot_be_processed(
    client, db_session, seed_accounts, treatment, amount
):
    employee = _employee(client, rate=12.5)
    _loan(db_session, employee["id"])
    draft = _draft(client, employee["id"])
    snapshot = db_session.get(PayStub, draft["stubs"][0]["id"]).benefits[0]
    rule = json.loads(snapshot.rule_json)
    rule.update(
        employer_taxable=True,
        employer_tax_treatment=treatment,
        taxable_employer_amount=amount,
    )
    snapshot.rule_json = json.dumps(rule)
    db_session.commit()
    response = client.post(f"/api/payroll/{draft['id']}/process")
    assert response.status_code == 409, response.text
    assert "tax treatment" in response.json()["detail"].lower()
    db_session.expire_all()
    assert db_session.get(PayRun, draft["id"]).status == PayRunStatus.DRAFT
    assert db_session.query(Transaction).count() == 0


def _plain_benefit(db, employee_id):
    """A benefit that tracks no loan balance (an HSA-like deduction)."""
    from app.models.benefits import BenefitCode, BenefitRate, EmployeeBenefit

    code = BenefitCode(
        code="HSA-STAGED",
        name="HSA",
        kind="both",
        category="posttax",
        calc_method="fixed_amount",
        employer_calc_method="fixed_amount",
    )
    db.add(code)
    db.flush()
    db.add(
        BenefitRate(
            benefit_code_id=code.id,
            effective_from=date(2026, 1, 1),
            employee_rate=40,
            employer_rate=20,
        )
    )
    db.add(EmployeeBenefit(employee_id=employee_id, benefit_code_id=code.id))
    db.commit()
    return code


def _make_legacy(db, run):
    """Stage-before-reservations state: no marker on the benefit lines and no
    history baseline on the stub."""
    stub = db.get(PayStub, run["stubs"][0]["id"])
    detail = json.loads(stub.detail_json or "{}")
    detail.pop("payroll_history", None)
    for key in [k for k in detail if "history" in k]:
        detail.pop(key)
    stub.detail_json = json.dumps(detail)
    for snapshot in stub.benefits:
        rule = json.loads(snapshot.rule_json)
        rule.pop("draft_reservation", None)
        snapshot.rule_json = json.dumps(rule)
    db.commit()


def test_a_legacy_draft_with_no_loan_cancels_and_refunds_its_ytd_exactly(
    client, db_session, seed_accounts
):
    """A draft from before reservations were recorded used to be impossible to
    process (no verified history) and impossible to cancel (unverifiable
    reservations): stuck. What staging did to year-to-date is exactly
    knowable, so it is refunded, and the person is told nothing needs review."""
    from app.models.benefits import BenefitYTD

    employee = _employee(client, rate=12.5)
    code = _plain_benefit(db_session, employee["id"])
    run = _draft(client, employee["id"])
    ytd = db_session.query(BenefitYTD).filter_by(benefit_code_id=code.id).one()
    assert (ytd.employee_amount, ytd.employer_amount) == (40, 20)
    _make_legacy(db_session, run)

    held = client.post(f"/api/payroll/{run['id']}/process")
    assert held.status_code == 409  # still cannot be paid unverified

    cancelled = client.post(f"/api/payroll/{run['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["loan_review"] == []
    db_session.expire_all()
    ytd = db_session.query(BenefitYTD).filter_by(benefit_code_id=code.id).one()
    assert (ytd.employee_amount, ytd.employer_amount) == (0, 0)
    assert db_session.get(PayRun, run["id"]).status == PayRunStatus.VOID
    # and the work can be staged again
    assert _draft(client, employee["id"])["status"] == "draft"


def test_a_legacy_draft_with_a_loan_needs_the_loan_balance_acknowledged(
    client, db_session, seed_accounts
):
    from app.models.benefits import BenefitYTD

    employee = _employee(client, rate=12.5)
    code, assignment = _loan(db_session, employee["id"])
    run = _draft(client, employee["id"])
    _make_legacy(db_session, run)
    before_balance = Decimal(str(assignment.balance_remaining))  # 150 after staging

    refused = client.post(f"/api/payroll/{run['id']}/cancel")
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "legacy_loan_review"
    assert detail["loans"] == [
        {
            "employee_id": employee["id"],
            "code": "LOAN-STAGED",
            "name": "Loan",
            "amount": "100.00",
        }
    ]
    db_session.expire_all()
    assert db_session.get(PayRun, run["id"]).status == PayRunStatus.DRAFT
    ytd = db_session.query(BenefitYTD).filter_by(benefit_code_id=code.id).one()
    assert (ytd.employee_amount, ytd.employer_amount) == (100, 50)  # untouched

    done = client.post(
        f"/api/payroll/{run['id']}/cancel", json={"acknowledge_unverified_loans": True}
    )
    assert done.status_code == 200, done.text
    assert done.json()["loan_review"][0]["code"] == "LOAN-STAGED"
    db_session.expire_all()
    ytd = db_session.query(BenefitYTD).filter_by(benefit_code_id=code.id).one()
    assert (ytd.employee_amount, ytd.employer_amount) == (0, 0)
    # the loan balance is NOT guessed at: it stays for the person to check
    assert (
        Decimal(str(db_session.get(type(assignment), assignment.id).balance_remaining))
        == before_balance
    )
