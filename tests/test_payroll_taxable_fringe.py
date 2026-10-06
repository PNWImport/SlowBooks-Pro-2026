"""Ordinary noncash fringe wages use explicit, immutable classification.

IRS Publications 15/15-B permit aggregation with regular wages. These tests
use the published 2026 6.2%/1.45% FICA rates, $184,500 Social Security base,
$200,000 Additional Medicare threshold and $7,000 FUTA base. They do not
classify GTL, value a benefit, or implement employee-tax gross-up.
https://www.irs.gov/publications/p15
https://www.irs.gov/publications/p15b
"""

import json
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest

from app.models.accounts import Account
from app.models.benefits import BenefitCode, PayStubBenefit
from app.models.payroll import Employee, PayRun, PayRunStatus, PayStub
from app.models.transactions import Transaction, TransactionLine
from app.routes.payroll.ytd import employee_ytd
from app.services.payroll_service import calculate_withholdings
from app.services.payroll_wages import federal_wages, fica_wages, state_wages
from app.services.tax_forms.efw2 import generate_efw2
from app.services.tax_forms.form_940 import compute_940
from app.services.tax_forms.form_941 import compute_941
from app.services.tax_forms.state_sui import compute_sui
from app.services.tax_forms.w2_w3 import compute_w2
from tests.test_benefits_engine import _code, _emp, _enroll


def test_ordinary_fringe_increases_taxes_without_paying_the_noncash_amount():
    result = calculate_withholdings(
        Decimal("2000"), work_state="TX", taxable_employer=Decimal("100")
    )
    assert result["gross"] == Decimal("2000.00")
    assert result["federal"] == Decimal("168.15")
    assert result["ss"] == result["employer_ss"] == Decimal("130.20")
    assert result["medicare"] == result["employer_medicare"] == Decimal("30.45")
    assert result["futa"] == Decimal("12.60")
    assert result["net"] == Decimal("1671.20")


@pytest.mark.parametrize(
    "prior,field,expected",
    [
        ("184000", "ss", "31.00"),
        ("184500", "ss", "0.00"),
        ("199500", "medicare", "44.85"),
        ("200000", "medicare", "49.35"),
        ("6500", "futa", "3.00"),
        ("7000", "futa", "0.00"),
        ("0", "ss", "130.20"),
    ],
)
def test_fringe_and_explicit_fica_ytd_share_the_annual_bases(prior, field, expected):
    result = calculate_withholdings(
        Decimal("2000"),
        work_state="TX",
        taxable_employer=Decimal("100"),
        ytd_gross=Decimal("250000"),
        ytd_fica=Decimal(prior),
    )
    assert result[field] == Decimal(expected)


@pytest.mark.parametrize("amount", ["-0.01", "NaN", "Infinity", "-Infinity"])
def test_invalid_taxable_value_cannot_enter_a_tax_calculation(amount):
    with pytest.raises(ValueError):
        calculate_withholdings(
            Decimal("2000"), work_state="TX", taxable_employer=Decimal(amount)
        )


def _fringe(client, *, amount=100, classified=True, **changes):
    code_name = changes.pop("code_name", "FRINGE")
    body = {
        "kind": "benefit",
        "employer_taxable": True,
        "reduces_federal": False,
        "reduces_state": False,
        "reduces_fica": False,
        "rate": {"employee_rate": 0, "employer_rate": amount},
    }
    if classified:
        body["employer_tax_treatment"] = "fully_taxable"
    body.update(changes)
    return _code(client, code_name, **body)


def _create_run(client, employee_ids, *, gross="2000", pay_date="2026-06-20"):
    return client.post(
        "/api/payroll",
        json={
            "period_start": "2026-06-01",
            "period_end": "2026-06-14",
            "pay_date": pay_date,
            "stubs": [
                {"employee_id": employee_id, "gross_override": gross}
                for employee_id in employee_ids
            ],
        },
    )


def test_processed_fringe_posts_once_and_snapshot_survives_code_edits(
    client, db_session, seed_accounts
):
    employee = _emp(client, rate=25, work_state="TX")
    code = _fringe(client)
    _enroll(client, employee["id"], code["id"])
    response = _create_run(client, [employee["id"]])
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    posted = client.post(f"/api/payroll/{run_id}/process")
    assert posted.status_code == 200, posted.text
    run = db_session.get(PayRun, run_id)
    stub = db_session.query(PayStub).filter_by(pay_run_id=run_id).one()
    assert stub.gross_pay == Decimal("2000.00")
    assert stub.net_pay == Decimal("1671.20")
    assert stub.employer_benefits == Decimal("100.00")
    assert stub.ss_tax == Decimal("130.20")
    assert stub.medicare_tax == Decimal("30.45")
    snapshot = stub.benefits[0]
    rule = json.loads(snapshot.rule_json)
    assert rule["employer_tax_treatment"] == "fully_taxable"
    assert Decimal(rule["taxable_employer_amount"]) == Decimal("100.00")

    lines = (
        db_session.query(TransactionLine)
        .filter_by(transaction_id=run.transaction_id)
        .all()
    )
    by_account = {}
    for line in lines:
        number = db_session.get(Account, line.account_id).account_number
        by_account[number] = by_account.get(number, Decimal("0")) + line.debit
    assert by_account["6110"] == Decimal("2000.00")
    assert by_account["6150"] == Decimal("100.00")
    assert sum(line.debit for line in lines) == sum(line.credit for line in lines)

    changed = client.put(
        f"/api/benefits/codes/{code['id']}",
        json={"employer_taxable": False, "employer_tax_treatment": None},
    )
    assert changed.status_code == 200, changed.text
    db_session.expire_all()
    wages = compute_w2(db_session, 2026, employee["id"])
    assert wages["box1_federal_wages"] == Decimal("2100.00")
    assert wages["box3_ss_wages"] == Decimal("2100.00")
    assert wages["box5_medicare_wages"] == Decimal("2100.00")
    assert wages["box16_state_wages"] == Decimal("2100.00")
    ytd = employee_ytd(db_session, employee["id"], 2026)
    assert ytd["gross"] == Decimal("2000.00")
    assert ytd["taxable_gross"] == ytd["fica_wages"] == Decimal("2100.00")


@pytest.mark.parametrize("gross", ["0", "1"])
def test_insufficient_cash_fringe_is_rejected_atomically(
    client, db_session, seed_accounts, gross
):
    employee = _emp(client, work_state="TX")
    code = _fringe(client)
    _enroll(client, employee["id"], code["id"])
    response = _create_run(client, [employee["id"]], gross=gross)
    assert response.status_code == 422, response.text
    assert db_session.query(PayRun).count() == 0
    assert db_session.query(PayStub).count() == 0
    assert db_session.query(PayStubBenefit).count() == 0
    assert db_session.query(Transaction).count() == 0


def test_unclassified_taxable_fringe_rejects_the_entire_multi_employee_run(
    client, db_session, seed_accounts
):
    ordinary = _emp(client, first_name="Ordinary", work_state="TX")
    unsupported = _emp(client, first_name="GTL", work_state="TX")
    code = _fringe(client, classified=False)
    _enroll(client, unsupported["id"], code["id"])
    response = _create_run(client, [ordinary["id"], unsupported["id"]])
    assert response.status_code == 422, response.text
    assert db_session.query(PayRun).count() == 0
    assert db_session.query(PayStub).count() == 0
    assert db_session.query(PayStubBenefit).count() == 0
    assert db_session.query(Transaction).count() == 0


def test_seeded_group_term_life_is_reported_only_and_does_not_block_payroll(
    client, db_session, seed_accounts
):
    """Group-term life up to $50,000 is not wages. The seeded code ships as
    reported-only, so enrolling someone with an employer amount no longer
    blocks their payroll — and, equally, adds nothing to their wages."""
    seeded = client.post("/api/benefits/codes/seed-standard")
    assert seeded.status_code == 200, seeded.text
    gtl = next(code for code in seeded.json() if code["code"] == "GTL")
    assert gtl["employer_taxable"] is True
    assert gtl["employer_tax_treatment"] == "reported_only"
    employee = _emp(client, work_state="TX")
    _enroll(client, employee["id"], gtl["id"], employer_rate=100)
    response = _create_run(client, [employee["id"]])
    assert response.status_code == 201, response.text
    stub = db_session.get(PayStub, response.json()["stubs"][0]["id"])
    assert federal_wages(stub) == state_wages(stub) == fica_wages(stub)
    assert Decimal(str(stub.gross_pay)) == fica_wages(stub)  # nothing added


def test_an_unclassified_taxable_employer_code_still_blocks_payroll(
    client, db_session, seed_accounts
):
    """The safeguard stays for a code nobody has classified: guessing at
    wages is worse than stopping, and the message names the way out."""
    code = _fringe(client)  # taxable employer contribution, no treatment
    client.put(
        f"/api/benefits/codes/{code['id']}", json={"employer_tax_treatment": None}
    )
    employee = _emp(client, work_state="TX")
    _enroll(client, employee["id"], code["id"])
    response = _create_run(client, [employee["id"]])
    assert response.status_code == 422, response.text
    assert "reported only" in response.json()["detail"].lower()
    assert db_session.query(PayRun).count() == 0


def test_a_blocked_code_is_unblocked_by_classifying_it_reported_only(
    client, db_session, seed_accounts
):
    code = _fringe(client)
    client.put(
        f"/api/benefits/codes/{code['id']}", json={"employer_tax_treatment": None}
    )
    employee = _emp(client, work_state="TX")
    _enroll(client, employee["id"], code["id"])
    assert _create_run(client, [employee["id"]]).status_code == 422

    fixed = client.put(
        f"/api/benefits/codes/{code['id']}",
        json={"employer_tax_treatment": "reported_only"},
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["employer_tax_treatment"] == "reported_only"
    assert _create_run(client, [employee["id"]]).status_code == 201


def test_reported_only_needs_a_taxable_employer_contribution(client, seed_accounts):
    r = client.post(
        "/api/benefits/codes",
        json={
            "code": "NOTAX",
            "name": "Not taxable",
            "kind": "benefit",
            "category": "posttax",
            "calc_method": "fixed_amount",
            "employer_taxable": False,
            "employer_tax_treatment": "reported_only",
        },
    )
    assert r.status_code == 400, r.text


def test_employee_exclusion_and_taxable_employer_value_remain_separate(
    client, db_session, seed_accounts
):
    employee = _emp(client, work_state="TX")
    code = _fringe(
        client,
        kind="both",
        reduces_federal=True,
        reduces_state=True,
        reduces_fica=True,
        rate={"employee_rate": 100, "employer_rate": 100},
    )
    _enroll(client, employee["id"], code["id"])
    response = _create_run(client, [employee["id"]])
    assert response.status_code == 201, response.text
    stub = response.json()["stubs"][0]
    # $2,000 cash + $100 fringe - $100 qualified employee deduction:
    # wages for taxes are $2,000; cash also funds the employee deduction.
    assert Decimal(str(stub["pretax_deductions"])) == Decimal("100.00")
    assert Decimal(str(stub["federal_tax"])) == Decimal("156.15")
    assert Decimal(str(stub["ss_tax"])) == Decimal("124.00")
    assert Decimal(str(stub["medicare_tax"])) == Decimal("29.00")
    assert Decimal(str(stub["net_pay"])) == Decimal("1590.85")
    stored = db_session.get(PayStub, stub["id"])
    assert federal_wages(stored) == state_wages(stored) == fica_wages(stored) == 2000


@pytest.mark.parametrize("classified", [True, False])
def test_paystub_pdf_identifies_noncash_value_without_inventing_legacy_wages(
    db_session, classified
):
    from pypdf import PdfReader

    from app.services.paystub_pdf import generate_paystub_pdf

    employee = Employee(first_name="PDF", last_name="Fringe", work_state="TX")
    stub = _paid(db_session, employee, date(2026, 1, 16), "2000")
    rule = {"employer_taxable": True}
    if classified:
        rule.update(
            employer_tax_treatment="fully_taxable", taxable_employer_amount="100"
        )
    _snapshot(db_session, stub, rule=rule)
    stub.net_pay = Decimal("1671.20" if classified else "1690.85")
    stub.federal_tax = Decimal("168.15" if classified else "156.15")
    stub.ss_tax = Decimal("130.20" if classified else "124.00")
    stub.medicare_tax = Decimal("30.45" if classified else "29.00")
    db_session.flush()
    document = generate_paystub_pdf(
        stub,
        employee,
        stub.pay_run,
        {"name": "QA Fringe"},
        {"gross": stub.gross_pay, "net": stub.net_pay},
        [stub],
    )
    reader = PdfReader(BytesIO(document))
    assert len(reader.pages) == 1
    assert float(reader.pages[0].mediabox.width) == pytest.approx(612, abs=0.1)
    assert float(reader.pages[0].mediabox.height) == pytest.approx(792, abs=0.1)
    text = reader.pages[0].extract_text()
    assert "$2,000.00" in text
    assert f"${stub.net_pay:,.2f}" in text
    label = "Taxable noncash employer contributions"
    if classified:
        assert text.count(label) == 1
        assert "$100.00" in text
        assert "Included in tax wages" in text
    else:
        assert label not in text


def test_posttax_match_cannot_silently_recompute_a_taxable_employer_value(
    client, db_session, seed_accounts
):
    employee = _emp(client, work_state="TX")
    code = _fringe(
        client,
        kind="both",
        category="posttax",
        employer_calc_method="match_percent",
        rate={"employee_rate": 100, "employer_rate": 50},
    )
    _enroll(client, employee["id"], code["id"])
    response = _create_run(client, [employee["id"]])
    assert response.status_code == 422, response.text
    assert db_session.query(PayRun).count() == 0
    assert db_session.query(PayStub).count() == 0


@pytest.mark.parametrize("classified", [False, True])
def test_zero_employer_value_preserves_ordinary_cash_payroll(
    client, db_session, seed_accounts, classified
):
    employee = _emp(client, work_state="TX")
    code = _fringe(client, amount=0, classified=classified)
    _enroll(client, employee["id"], code["id"])
    response = _create_run(client, [employee["id"]])
    assert response.status_code == 201, response.text
    stub = response.json()["stubs"][0]
    assert Decimal(str(stub["ss_tax"])) == Decimal("124.00")
    assert Decimal(str(stub["medicare_tax"])) == Decimal("29.00")
    assert Decimal(str(stub["net_pay"])) == Decimal("1690.85")


def _snapshot(db, stub, employer="100", rule=None, employee="0", **flags):
    snapshot = PayStubBenefit(
        pay_stub=stub,
        code="FRINGE",
        name="Immutable fringe",
        kind="benefit",
        category="pretax",
        calc_method="fixed_amount",
        employee_amount=Decimal(employee),
        employer_amount=Decimal(employer),
        rule_json=json.dumps(rule) if rule is not None else None,
        **flags,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _paid(db, employee, paid, gross, *, pretax="0", tips=("0", "0")):
    run = PayRun(
        period_start=paid,
        period_end=paid,
        pay_date=paid,
        status=PayRunStatus.PROCESSED,
    )
    stub = PayStub(
        employee=employee,
        pay_run=run,
        gross_pay=Decimal(gross),
        pretax_deductions=Decimal(pretax),
        reported_tips=Decimal(tips[0]),
        paycheck_tips=Decimal(tips[1]),
    )
    db.add(stub)
    db.flush()
    return stub


@pytest.mark.parametrize(
    "rule",
    [
        None,
        {"employer_taxable": True},
        {"employer_taxable": True, "employer_tax_treatment": "fully_taxable"},
        {"employer_tax_treatment": "fully_taxable", "taxable_employer_amount": "0"},
    ],
)
def test_legacy_and_explicit_zero_snapshots_never_infer_current_taxability(
    db_session, rule
):
    employee = Employee(first_name="Legacy", last_name="Fringe")
    stub = _paid(db_session, employee, date(2026, 1, 16), "2000")
    snapshot = _snapshot(db_session, stub, rule=rule)
    snapshot.benefit_code = BenefitCode(
        code="FRINGE",
        name="Current changed code",
        kind="benefit",
        employer_taxable=True,
        employer_tax_treatment="fully_taxable",
    )
    db_session.flush()
    assert federal_wages(stub) == state_wages(stub) == fica_wages(stub) == 2000
    assert compute_940(db_session, 2026)["total_payments"] == Decimal("2000.00")


def test_fringe_reports_preserve_tips_qualified_exclusions_caps_and_actual_tax(
    db_session,
):
    employee = Employee(first_name="Reported", last_name="Fringe", work_state="TX")
    prior = _paid(db_session, employee, date(2026, 1, 16), "6500", pretax="500")
    _snapshot(
        db_session,
        prior,
        employer="1000",
        employee="500",
        reduces_federal=True,
        reduces_state=True,
        reduces_fica=True,
        rule={
            "employer_tax_treatment": "fully_taxable",
            "taxable_employer_amount": "1000",
        },
    )
    current = _paid(
        db_session, employee, date(2026, 4, 17), "2000", tips=("200", "100")
    )
    _snapshot(
        db_session,
        current,
        rule={
            "employer_tax_treatment": "fully_taxable",
            "taxable_employer_amount": "100",
        },
    )
    prior.futa_tax = Decimal("42.00")
    current.futa_tax = Decimal("0.00")
    current.federal_tax = Decimal("168.15")
    current.ss_tax = Decimal("130.20")
    current.medicare_tax = Decimal("30.45")
    db_session.flush()

    w2 = compute_w2(db_session, 2026, employee.id)
    assert w2["box1_federal_wages"] == w2["box16_state_wages"] == Decimal("9100.00")
    assert w2["box3_ss_wages"] == Decimal("8800.00")
    assert w2["box7_ss_tips"] == Decimal("300.00")
    assert w2["box5_medicare_wages"] == Decimal("9100.00")
    assert w2["box2_federal_tax_withheld"] == Decimal("168.15")
    q2 = compute_941(db_session, 2026, 2)
    assert q2["total_wages"] == q2["medicare_wages"] == Decimal("2100.00")
    assert q2["social_security_wages"] == Decimal("1800.00")
    assert q2["social_security_tips"] == Decimal("300.00")
    annual = compute_940(db_session, 2026)
    assert annual["total_payments"] == Decimal("9600.00")
    assert annual["exempt_payments"] == Decimal("500.00")
    assert annual["excess_payments"] == Decimal("2100.00")
    assert annual["futa_taxable_wages"] == Decimal("7000.00")
    assert annual["total_futa_tax"] == Decimal("42.00")

    text, _ = generate_efw2(db_session, 2026, {"name": "QA", "ein": "91-1234567"})
    rw = next(line for line in text.split("\r\n") if line.startswith("RW"))
    assert rw[187:198] == "00000910000"  # Federal wages, positions 188-198
    assert rw[209:220] == "00000880000"  # Social Security wages, 210-220
    assert rw[231:242] == "00000910000"  # Medicare wages, 232-242
    assert rw[253:264] == "00000030000"  # Social Security tips, 254-264


@pytest.mark.parametrize(
    "prior,field,expected",
    [
        ("184000", "ss_tax", "31.00"),
        ("199500", "medicare_tax", "44.85"),
        ("6500", "futa_tax", "3.00"),
    ],
)
def test_regular_run_uses_prior_immutable_fringe_in_cumulative_tax_bases(
    client, db_session, seed_accounts, prior, field, expected
):
    employee = _emp(client, work_state="TX")
    prior_stub = _paid(
        db_session,
        db_session.get(Employee, employee["id"]),
        date(2026, 1, 16),
        str(Decimal(prior) - 100),
    )
    _snapshot(
        db_session,
        prior_stub,
        rule={
            "employer_tax_treatment": "fully_taxable",
            "taxable_employer_amount": "100",
        },
    )
    db_session.commit()
    code = _fringe(client)
    _enroll(client, employee["id"], code["id"])
    response = _create_run(client, [employee["id"]])
    assert response.status_code == 201, response.text
    assert Decimal(str(response.json()["stubs"][0][field])) == Decimal(expected)


@pytest.mark.parametrize("rate", [Decimal("0"), Decimal("0.027")])
def test_sui_reports_exact_fringe_wages_even_at_zero_rate_and_partial_cap(
    db_session, rate
):
    # TX's modeled annual unemployment base is $9,000. This paycheck's
    # compensation is $2,100 but only $500 remains below the state cap.
    result = calculate_withholdings(
        Decimal("2000"),
        work_state="TX",
        taxable_employer=Decimal("100"),
        ytd_gross=Decimal("8500"),
        ytd_fica=Decimal("8500"),
        suta_rate=rate,
    )
    assert Decimal(str(result["detail"]["employer_suta_wages"])) == Decimal("500.00")
    employee = Employee(first_name="State", last_name="Fringe", work_state="TX")
    stub = _paid(db_session, employee, date(2026, 4, 17), "2000")
    _snapshot(
        db_session,
        stub,
        rule={
            "employer_tax_treatment": "fully_taxable",
            "taxable_employer_amount": "100",
        },
    )
    stub.suta_tax = result["suta"]
    stub.detail_json = json.dumps(
        {key: str(value) for key, value in result["detail"].items()}
    )
    db_session.flush()
    report = compute_sui(db_session, 2026, 2, "TX")
    assert report["total_wages"] == Decimal("2100.00")
    assert report["total_suta_taxable_wages"] == Decimal("500.00")
    assert report["total_suta_tax"] == (Decimal("500") * rate).quantize(Decimal("0.01"))


@pytest.mark.parametrize("bad", [None, "not-a-number", "NaN", "-1", "99999"])
def test_a_garbled_taxable_snapshot_fails_with_the_named_error(bad):
    """Corrupt snapshot data must stop payroll loudly, always as ValueError."""
    import json
    from types import SimpleNamespace

    from app.services.payroll_wages import taxable_employer_wages

    stub = SimpleNamespace(
        benefits=[
            SimpleNamespace(
                employer_amount="10.00",
                rule_json=json.dumps(
                    {
                        "employer_tax_treatment": "fully_taxable",
                        "taxable_employer_amount": bad,
                    }
                ),
            )
        ]
    )
    with pytest.raises(ValueError, match="Invalid immutable taxable employer"):
        taxable_employer_wages(stub)
