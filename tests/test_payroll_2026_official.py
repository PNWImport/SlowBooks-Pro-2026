"""Known answers from IRS Pub 15-T (2026) and state premium guidance.

IRS: https://www.irs.gov/publications/p15t, Worksheet 1A and section 1.
WA: https://paidleave.wa.gov/employer-roles-responsibilities/
WA Cares: https://wacaresfund.wa.gov/help-support/frequently-asked-questions
CA: https://edd.ca.gov/en/payroll_taxes/rates_and_withholding/
NY: https://paidfamilyleave.ny.gov/2026
OR: https://www.oregon.gov/dor/programs/businesses/pages/statewide-transit-tax.aspx
The expected dollars come from these published rules, independently of the
production constants and calculator implementation.
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from app.services.payroll_service import calculate_withholdings, federal_income_tax
from app.services.state_tax import get_engine


@pytest.mark.parametrize(
    "filing_status,multiple_jobs,expected",
    [
        ("single", False, "156.15"),
        ("married", False, "76.15"),
        ("head_of_household", False, "114.92"),
        ("single", True, "270.19"),
        ("married", True, "156.15"),
        ("head_of_household", True, "201.31"),
    ],
)
def test_2026_federal_biweekly_known_answers(filing_status, multiple_jobs, expected):
    assert federal_income_tax(
        Decimal("2000"), 26, filing_status, multiple_jobs=multiple_jobs
    ) == Decimal(expected)


@pytest.mark.parametrize(
    "multiple_jobs,expected", [(False, "114.92"), (True, "242.04")]
)
def test_worksheet_1a_applies_income_deductions_credits_and_extra(
    multiple_jobs, expected
):
    assert federal_income_tax(
        Decimal("2000"),
        26,
        "single",
        multiple_jobs=multiple_jobs,
        other_income_annual=Decimal("6000"),
        deductions_annual=Decimal("2600"),
        dependents_amount=Decimal("2000"),
        extra_withholding=Decimal("20"),
    ) == Decimal(expected)


@pytest.mark.parametrize(
    "filing_status,multiple_jobs,zero_band",
    [
        ("single", False, "16100"),
        ("married", False, "32200"),
        ("head_of_household", False, "24150"),
        ("single", True, "8050"),
        ("married", True, "16100"),
        ("head_of_household", True, "12075"),
    ],
)
@pytest.mark.parametrize(
    "offset,expected", [("-1", "0.00"), ("0", "0.00"), ("1", "0.10")]
)
def test_2026_federal_zero_band_boundaries(
    filing_status, multiple_jobs, zero_band, offset, expected
):
    assert federal_income_tax(
        Decimal(zero_band) + Decimal(offset),
        1,
        filing_status,
        multiple_jobs=multiple_jobs,
    ) == Decimal(expected)


@pytest.mark.parametrize(
    "filing_status,annual_wages,expected",
    [
        ("single", "108938", "20512.00"),
        ("single", "136163", "29224.00"),
        ("single", "328350", "96489.63"),
        ("married", "400450", "103291.75"),
        ("head_of_household", "332375", "95585.50"),
    ],
)
def test_checkbox_uses_published_base_tax_at_rounded_boundaries(
    filing_status, annual_wages, expected
):
    assert federal_income_tax(
        Decimal(annual_wages), 1, filing_status, multiple_jobs=True
    ) == Decimal(expected)


def _state(state="WA", **overrides):
    kwargs = dict(
        gross=Decimal("2000"),
        taxable=Decimal("2000"),
        ytd_gross=Decimal("0"),
        pay_periods=26,
        hours=Decimal("0"),
        filing_status="single",
        wc_class_code=None,
    )
    kwargs.update(overrides)
    return get_engine(state).calculate(**kwargs)


@pytest.mark.parametrize(
    "ytd,employee,employer",
    [
        ("176100", "16.14", "6.46"),
        ("184000", "4.04", "1.61"),
        ("184500", "0.00", "0.00"),
        ("185000", "0.00", "0.00"),
    ],
)
def test_wa_2026_pfml_cap_and_uncapped_cares(ytd, employee, employer):
    result = _state(ytd_gross=Decimal(ytd))
    assert result.detail["WA PFML (employee)"] == Decimal(employee)
    assert result.detail["WA PFML (employer)"] == Decimal(employer)
    assert result.detail["WA Cares"] == Decimal("11.60")


def test_wa_premiums_exclude_tips_and_keep_gross_wages_when_taxable_is_zero():
    result = _state(gross=Decimal("2500"), taxable=Decimal("0"), tips=Decimal("500"))
    assert result.income_tax == 0
    assert result.detail["WA PFML (employee)"] == Decimal("16.14")
    assert result.detail["WA PFML (employer)"] == Decimal("6.46")
    assert result.detail["WA Cares"] == Decimal("11.60")


def test_wa_tip_exclusion_does_not_reduce_fica_or_federal_wages():
    result = calculate_withholdings(
        Decimal("2500"), tips=Decimal("500"), work_state="WA"
    )
    assert result["federal"] == federal_income_tax(Decimal("2500"), 26, "single")
    assert result["ss"] == Decimal("155.00")
    assert result["detail"]["WA PFML (employee)"] == Decimal("16.14")
    assert result["detail"]["WA Cares"] == Decimal("11.60")


@pytest.mark.parametrize(
    "state,full_employee,full_employer,crossing_employee,crossing_employer",
    [
        ("CO", "8.80", "8.80", "2.20", "2.20"),
        ("MA", "9.20", "8.40", "2.30", "2.10"),
        ("DE", "8.00", "8.00", "2.00", "2.00"),
    ],
)
def test_paid_leave_caps_follow_2026_social_security_base(
    state, full_employee, full_employer, crossing_employee, crossing_employer
):
    full = _state(state, ytd_gross=Decimal("176100"))
    crossing = _state(state, ytd_gross=Decimal("184000"))
    capped = _state(state, ytd_gross=Decimal("184500"))
    assert (full.employee_other, full.employer_other) == (
        Decimal(full_employee),
        Decimal(full_employer),
    )
    assert (crossing.employee_other, crossing.employer_other) == (
        Decimal(crossing_employee),
        Decimal(crossing_employer),
    )
    assert capped.employee_other == capped.employer_other == 0


def _employee_and_tipped_ytd(client, db_session):
    from app.models.payroll import PayRun, PayRunStatus, PayRunType, PayStub

    response = client.post(
        "/api/employees",
        json={
            "first_name": "WA",
            "last_name": "Premium",
            "pay_type": "hourly",
            "pay_rate": 25,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "WA",
        },
    )
    assert response.status_code == 201, response.text
    employee = response.json()
    # Federal/FICA gross has passed its cap, while WA's non-tip premium wages
    # are only $184,000. A voided tipped check must contribute to neither YTD.
    for status in (PayRunStatus.PROCESSED, PayRunStatus.VOID):
        run = PayRun(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 14),
            pay_date=date(2026, 1, 15),
            status=status,
            run_type=PayRunType.OFF_CYCLE,
        )
        db_session.add(run)
        db_session.flush()
        db_session.add(
            PayStub(
                pay_run_id=run.id,
                employee_id=employee["id"],
                gross_pay=Decimal("185000"),
                reported_tips=Decimal("400"),
                paycheck_tips=Decimal("600"),
                net_pay=Decimal("0"),
            )
        )
    db_session.commit()
    return employee


def test_regular_paystub_excludes_both_tip_types_and_preserves_ytd_cap(
    client, db_session, seed_accounts
):
    employee = _employee_and_tipped_ytd(client, db_session)
    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-06-01",
            "period_end": "2026-06-14",
            "pay_date": "2026-06-20",
            "stubs": [
                {
                    "employee_id": employee["id"],
                    "hours": 80,
                    "reported_tips": 200,
                    "paycheck_tips": 300,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    stub = response.json()["stubs"][0]
    assert stub["gross_pay"] == 2500
    from app.models.payroll import PayStub

    detail = json.loads(db_session.get(PayStub, stub["id"]).detail_json)
    assert Decimal(str(detail["WA PFML (employee)"])) == Decimal("4.04")
    assert Decimal(str(detail["WA PFML (employer)"])) == Decimal("1.61")
    assert Decimal(str(detail["WA Cares"])) == Decimal("11.60")
    assert stub["ss_tax"] == 0


def test_gross_up_uses_non_tip_ytd_premium_wages(
    client, db_session, seed_accounts, monkeypatch
):
    from app.routes.payroll import runs

    class PayrollDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 20)

    monkeypatch.setattr(runs, "date", PayrollDate)
    employee = _employee_and_tipped_ytd(client, db_session)
    response = client.post(
        "/api/payroll/gross-up",
        json={"employee_id": employee["id"], "target_net": 100, "supplemental": False},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    # Medicare + PFML + Cares, no federal or SS on this check. Around $102.92
    # leaves $100 net; incorrectly treating tips as cap wages yields $102.07.
    assert Decimal("102.91") <= Decimal(str(result["gross"])) <= Decimal("102.93")
    assert abs(Decimal(str(result["net"])) - Decimal("100")) <= Decimal("0.01")


def test_retro_pay_uses_non_tip_ytd_premium_wages(client, db_session, seed_accounts):
    from app.models.payroll import PayStub

    employee = _employee_and_tipped_ytd(client, db_session)
    response = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-02-01",
            "period_end": "2026-02-01",
            "pay_date": "2026-02-05",
            "stubs": [{"employee_id": employee["id"], "hours": 1}],
        },
    )
    assert response.status_code == 201, response.text
    assert (
        client.post(f"/api/payroll/{response.json()['id']}/process").status_code == 200
    )
    response = client.post(
        "/api/payroll/retro-pay/apply",
        json={
            "employee_id": employee["id"],
            "new_rate": 100,
            "effective_date": "2026-02-01",
            "pay_date": "2026-06-20",
        },
    )
    assert response.status_code == 201, response.text
    stub = (
        db_session.query(PayStub)
        .filter_by(pay_run_id=response.json()["pay_run_id"])
        .one()
    )
    assert stub.gross_pay == Decimal("75.00")
    detail = json.loads(stub.detail_json)
    assert Decimal(detail["WA PFML (employee)"]) == Decimal("0.61")
    assert Decimal(detail["WA PFML (employer)"]) == Decimal("0.24")
    assert Decimal(detail["WA Cares"]) == Decimal("0.44")


@pytest.mark.parametrize("future_paycheck", [False, True])
def test_termination_payout_uses_non_tip_ytd_premium_wages(
    client, db_session, seed_accounts, future_paycheck
):
    from app.models.payroll import PayRun, PayRunStatus, PayRunType, PayStub
    from app.models.pto import PTOAccrual, PTOPolicy, PTOType, AccrualMethod

    employee = _employee_and_tipped_ytd(client, db_session)
    if future_paycheck:
        future_run = PayRun(
            period_start=date(2026, 12, 1),
            period_end=date(2026, 12, 15),
            pay_date=date(2026, 12, 15),
            run_type=PayRunType.OFF_CYCLE,
            status=PayRunStatus.PROCESSED,
        )
        db_session.add(future_run)
        db_session.flush()
        db_session.add(
            PayStub(
                pay_run_id=future_run.id,
                employee_id=employee["id"],
                gross_pay=Decimal("10000"),
                net_pay=Decimal("10000"),
            )
        )
        db_session.commit()
    policy = PTOPolicy(
        name="WA premium regression",
        pto_type=PTOType.VACATION,
        accrual_method=AccrualMethod.ANNUAL_GRANT,
        accrual_rate=20,
    )
    db_session.add(policy)
    db_session.flush()
    db_session.add(
        PTOAccrual(
            employee_id=employee["id"], policy_id=policy.id, balance=Decimal("20")
        )
    )
    db_session.commit()
    response = client.post(
        f"/api/employees/{employee['id']}/terminate",
        json={
            "termination_date": "2026-06-20",
            "reason": "involuntary",
            "payout_pto": True,
        },
    )
    assert response.status_code == 200, response.text
    stub = (
        db_session.query(PayStub)
        .filter_by(pay_run_id=response.json()["pto_payout_run_id"])
        .one()
    )
    assert stub.gross_pay == Decimal("500.00")
    detail = json.loads(stub.detail_json)
    assert Decimal(detail["WA PFML (employee)"]) == Decimal("4.04")
    assert Decimal(detail["WA PFML (employer)"]) == Decimal("1.61")
    assert Decimal(detail["WA Cares"]) == Decimal("2.90")


@pytest.mark.parametrize(
    "filing_status,multiple_jobs,annual_wages,published_base_tax",
    [
        ("single", False, "16100", "0.00"),
        ("single", False, "28500", "1240.00"),
        ("single", False, "66500", "5800.00"),
        ("single", False, "121800", "17966.00"),
        ("single", False, "217875", "41024.00"),
        ("single", False, "272325", "58448.00"),
        ("single", False, "656700", "192979.25"),
        ("married", False, "32200", "0.00"),
        ("married", False, "57000", "2480.00"),
        ("married", False, "133000", "11600.00"),
        ("married", False, "243600", "35932.00"),
        ("married", False, "435750", "82048.00"),
        ("married", False, "544650", "116896.00"),
        ("married", False, "800900", "206583.50"),
        ("head_of_household", False, "24150", "0.00"),
        ("head_of_household", False, "41850", "1770.00"),
        ("head_of_household", False, "91600", "7740.00"),
        ("head_of_household", False, "129850", "16155.00"),
        ("head_of_household", False, "225900", "39207.00"),
        ("head_of_household", False, "280350", "56631.00"),
        ("head_of_household", False, "664750", "191171.00"),
        ("single", True, "8050", "0.00"),
        ("single", True, "14250", "620.00"),
        ("single", True, "33250", "2900.00"),
        ("single", True, "60900", "8983.00"),
        ("single", True, "108938", "20512.00"),
        ("single", True, "136163", "29224.00"),
        ("single", True, "328350", "96489.63"),
        ("married", True, "16100", "0.00"),
        ("married", True, "28500", "1240.00"),
        ("married", True, "66500", "5800.00"),
        ("married", True, "121800", "17966.00"),
        ("married", True, "217875", "41024.00"),
        ("married", True, "272325", "58448.00"),
        ("married", True, "400450", "103291.75"),
        ("head_of_household", True, "12075", "0.00"),
        ("head_of_household", True, "20925", "885.00"),
        ("head_of_household", True, "45800", "3870.00"),
        ("head_of_household", True, "64925", "8077.50"),
        ("head_of_household", True, "112950", "19603.50"),
        ("head_of_household", True, "140175", "28315.50"),
        ("head_of_household", True, "332375", "95585.50"),
    ],
)
def test_every_2026_annual_schedule_row_matches_irs_column_c(
    filing_status, multiple_jobs, annual_wages, published_base_tax
):
    # Dollar inputs include Worksheet 1A line 1g for the standard schedule.
    assert federal_income_tax(
        Decimal(annual_wages), 1, filing_status, multiple_jobs=multiple_jobs
    ) == Decimal(published_base_tax)


@pytest.mark.parametrize(
    "gross,expected", [("2500", "32.50"), ("45000", "585.00"), ("200000", "2600.00")]
)
def test_ca_sdi_2026_official_uncapped_known_answers(gross, expected):
    r = _state("CA", gross=Decimal(gross), taxable=Decimal("0"))
    assert r.income_tax == 0
    assert r.detail["CA SDI"] == Decimal(expected)


@pytest.mark.parametrize(
    "ytd,expected",
    [
        ("0", "8.64"),
        ("91237", "8.64"),
        ("95000", "1.51"),
        ("95349.53", "0.00"),
        ("95349.54", "0.00"),
        ("100000", "0.00"),
    ],
)
def test_ny_pfl_2026_official_rate_and_annual_cap(ytd, expected):
    r = _state(
        "NY", gross=Decimal("2000"), taxable=Decimal("0"), ytd_gross=Decimal(ytd)
    )
    assert r.income_tax == 0
    assert r.detail["NY PFL"] == Decimal(expected)
    assert r.detail["NY SDI"] == Decimal("1.20")


def test_oregon_transit_still_withheld_when_income_tax_wages_zero():
    r = _state("OR", gross=Decimal("2000"), taxable=Decimal("0"))
    assert r.income_tax == 0
    assert r.detail["OR statewide transit tax"] == Decimal("2.00")


@pytest.mark.parametrize(
    "ytd,expected", [("13000", "40.00"), ("17400", "4.00"), ("17600", "0.00")]
)
def test_ny_unemployment_uses_official_2026_wage_base(ytd, expected):
    # NY DOL: https://dol.ny.gov/nys-45-quarterly-reporting
    # Use an explicit synthetic employer experience rate to isolate the cap.
    result = calculate_withholdings(
        Decimal("2000"),
        work_state="NY",
        ytd_gross=Decimal(ytd),
        suta_rate=Decimal("0.02"),
    )
    assert result["suta"] == Decimal(expected)


def test_dedicated_state_catalog_matches_verified_2026_unemployment_bases():
    from app.services.state_tax import list_states

    catalog = {row["code"]: row for row in list_states()}
    assert catalog["WA"]["suta_wage_base"] == 78200
    assert catalog["NY"]["suta_wage_base"] == 17600
    assert catalog["OR"]["suta_wage_base"] == 56700
