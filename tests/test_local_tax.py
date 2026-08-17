# ============================================================================
# Local / municipal payroll tax coverage.
# ----------------------------------------------------------------------------
# Structural tests guard the locality-file mechanism (parse, validate,
# unknown-code visibility); arithmetic tests pin hand-derived figures for
# each basis semantic — work (Philadelphia, Louisville), higher_of (PA Act
# 32), residence (MD/IN county, OH school district, NYC), work_or_residence
# (Michigan credit), the Yonkers resident surcharge / nonresident wage tax
# split, and the PA LST flat installments. Integration tests confirm
# calculate_withholdings carries local tax into totals, net, and disposable
# earnings.
#
# All wage figures assume a $2,000 biweekly check (26 periods) unless stated.
# ============================================================================

from decimal import Decimal

import pytest

from app.services.local_tax import (
    LocalTaxTableError,
    calculate_local_taxes,
    coverage_report,
    get_locality,
    supported_localities,
)
from app.services.local_tax.engine import LocalityRule


def _calc(**overrides):
    kwargs = dict(
        work_locality=None,
        residence_locality=None,
        taxable=Decimal("2000"),
        pay_periods=26,
        filing_status="single",
        state_income_tax=Decimal("0"),
    )
    kwargs.update(overrides)
    return calculate_local_taxes(**kwargs)


def _rule(**overrides):
    raw = {
        "code": "ZZ-TEST",
        "name": "Testville",
        "state": "ZZ",
        "kind": "percent",
        "basis": "work",
        "resident_rate": "0.01",
    }
    raw.update(overrides)
    return LocalityRule(raw, "test.json")


# --- structural -------------------------------------------------------------


def test_locality_files_load_and_report():
    rows = coverage_report()
    states = {row["state"] for row in rows}
    assert {"PA", "OH", "NY", "MD", "IN", "KY", "MI"} <= states
    for row in rows:
        assert row["source"].startswith("http"), f"{row['file']} has no source"
        assert row["tax_year"], f"{row['file']} has no tax_year"


def test_supported_localities_nonempty_and_resolvable():
    codes = supported_localities()
    assert len(codes) >= 30
    for code in codes:
        assert get_locality(code) is not None


def test_get_locality_is_case_insensitive():
    assert get_locality("pa-philadelphia") is get_locality("PA-PHILADELPHIA")


def test_unknown_codes_are_reported_not_silent():
    result = _calc(work_locality="ZZ-NOPE", residence_locality="XX-ALSO-NOPE")
    assert result.employee == 0
    assert result.unknown == ["ZZ-NOPE", "XX-ALSO-NOPE"]


def test_no_localities_no_tax():
    result = _calc()
    assert result.employee == 0
    assert result.employer == 0
    assert result.detail == {}


def test_nonpositive_wages_produce_empty_result():
    result = _calc(work_locality="PA-PHILADELPHIA", taxable=Decimal("0"))
    assert result.employee == 0


# --- rule validation --------------------------------------------------------


def test_missing_code_rejected():
    with pytest.raises(LocalTaxTableError, match="no code"):
        LocalityRule({"name": "nameless"}, "test.json")


def test_bad_kind_rejected():
    with pytest.raises(LocalTaxTableError, match="kind"):
        _rule(kind="vibes")


def test_bad_basis_rejected():
    with pytest.raises(LocalTaxTableError, match="basis"):
        _rule(basis="astrology")


def test_brackets_kind_without_brackets_rejected():
    with pytest.raises(LocalTaxTableError, match="none defined"):
        _rule(kind="brackets")


def test_descending_brackets_rejected():
    with pytest.raises(LocalTaxTableError, match="ascend"):
        _rule(kind="brackets", brackets={"single": [["0", "0.01"], ["0", "0.02"]]})


# --- work basis (Philadelphia, Louisville) ----------------------------------
# Philadelphia: resident 3.75%, nonresident 3.44% of taxable wages.


def test_philadelphia_nonresident():
    result = _calc(work_locality="PA-PHILADELPHIA")
    assert result.employee == Decimal("68.80")  # 2000 * 0.0344


def test_philadelphia_resident():
    result = _calc(
        work_locality="PA-PHILADELPHIA", residence_locality="PA-PHILADELPHIA"
    )
    assert result.employee == Decimal("75.00")  # 2000 * 0.0375


def test_louisville_nonresident_rate_differs_from_resident():
    res = _calc(work_locality="KY-LOUISVILLE", residence_locality="KY-LOUISVILLE")
    nonres = _calc(work_locality="KY-LOUISVILLE")
    assert res.employee == Decimal("44.00")  # 2.2%
    assert nonres.employee == Decimal("29.00")  # 1.45%


def test_work_basis_ignores_residence_locality_tax_free_home():
    """Living in a no-rule locality changes nothing at the work city."""
    result = _calc(work_locality="OH-COLUMBUS", residence_locality=None)
    assert result.employee == Decimal("50.00")  # 2.5%


# --- higher_of basis (PA Act 32) --------------------------------------------
# Allentown nonresident 1.0%; Pittsburgh resident 3.0%; LST $52/yr → $2/period.


def test_pa_act32_takes_the_higher_residence_rate():
    result = _calc(work_locality="PA-ALLENTOWN", residence_locality="PA-PITTSBURGH")
    # max(1.0% work nonres, 3.0% residence res) = 3.0% → 60.00, plus work LST 2.00
    assert result.detail["Allentown local tax (unverified)"] == Decimal("60.00")
    assert result.detail["Allentown LST (unverified)"] == Decimal("2.00")
    assert result.employee == Decimal("62.00")


def test_pa_act32_takes_the_higher_work_rate():
    result = _calc(work_locality="PA-PITTSBURGH", residence_locality="PA-ALLENTOWN")
    # max(1.0% work nonres, 1.35% residence res) = 1.35% → 27.00, plus LST 2.00
    assert result.detail["Pittsburgh local tax (unverified)"] == Decimal("27.00")
    assert result.employee == Decimal("29.00")


def test_pa_lst_prorates_evenly_across_periods():
    weekly = _calc(work_locality="PA-SCRANTON", pay_periods=52)
    # Scranton LST $156/yr → $3.00/week
    assert weekly.detail["Scranton LST (unverified)"] == Decimal("3.00")


def test_pa_resident_working_at_home_city_pays_resident_rate():
    result = _calc(work_locality="PA-PITTSBURGH", residence_locality="PA-PITTSBURGH")
    assert result.detail["Pittsburgh local tax (unverified)"] == Decimal("60.00")


# --- residence basis (MD / IN counties, OH school district, NYC) ------------


def test_md_county_follows_residence_not_work():
    result = _calc(work_locality=None, residence_locality="MD-MONTGOMERY")
    assert result.employee == Decimal("64.00")  # 3.2%


def test_in_county_applies_alongside_work_city():
    """Live in Marion County, work in a locality with no rule."""
    result = _calc(work_locality="ZZ-NOWHERE", residence_locality="IN-MARION")
    assert result.employee == Decimal("40.40")  # 2.02%
    assert result.unknown == ["ZZ-NOWHERE"]


def test_oh_school_district_stacks_on_work_city():
    result = _calc(work_locality="OH-COLUMBUS", residence_locality="OH-SD-BEXLEY")
    # Columbus 2.5% work + Bexley SD 0.75% residence
    assert result.detail["Columbus local tax (unverified)"] == Decimal("50.00")
    assert result.detail[
        "Bexley CSD (2501) school district local tax (unverified)"
    ] == Decimal("15.00")
    assert result.employee == Decimal("65.00")


def test_nyc_brackets_are_progressive_and_annualized():
    result = _calc(work_locality="NY-NYC", residence_locality="NY-NYC")
    # Annual 52,000 single: 12,000@3.078% + 13,000@3.762% + 27,000@3.819%
    # = 369.36 + 489.06 + 1031.13 = 1889.55 / 26 = 72.675 → 72.68... but
    # rounding happens once at the period amount: 72.675 → 72.68? HALF_UP on
    # 72.675 with cent quantize → 72.68. Engine returned 72.72 in smoke —
    # recompute: 12000*.03078=369.36; (25000-12000)*.03762=489.06;
    # (50000-25000)*.03819=954.75; (52000-50000)*.03876=77.52;
    # total=1890.69; /26=72.719… → 72.72.
    assert result.employee == Decimal("72.72")


def test_nyc_nonresident_owes_nothing():
    """NYC's nonresident earnings tax was repealed — work there, live
    elsewhere (no local rule at home) → no NYC tax."""
    result = _calc(work_locality="NY-NYC", residence_locality=None)
    assert result.employee == Decimal("0.00")


# --- Yonkers ----------------------------------------------------------------


def test_yonkers_resident_surcharge_is_percent_of_state_tax():
    result = _calc(residence_locality="NY-YONKERS", state_income_tax=Decimal("100.00"))
    assert result.employee == Decimal("16.75")


def test_yonkers_nonresident_wage_tax():
    # Unknown residence = nonresident: the 0.5% wage tax applies.
    result = _calc(work_locality="NY-YONKERS", residence_locality=None)
    assert result.employee == Decimal("10.00")
    result = _calc(work_locality="NY-YONKERS", residence_locality="MD-MONTGOMERY")
    assert result.detail["Yonkers (nonresident) (unverified)"] == Decimal("10.00")


# --- work_or_residence basis (Michigan credit) ------------------------------


def test_mi_work_city_only():
    result = _calc(work_locality="MI-DETROIT", residence_locality=None)
    assert result.employee == Decimal("24.00")  # nonresident 1.2%


def test_mi_resident_of_work_city():
    result = _calc(work_locality="MI-DETROIT", residence_locality="MI-DETROIT")
    assert result.employee == Decimal("48.00")  # resident 2.4%


def test_mi_residence_city_credits_work_city_withholding():
    result = _calc(work_locality="MI-DETROIT", residence_locality="MI-GRAND-RAPIDS")
    # Detroit nonres 1.2% = 24.00; GR resident 1.5% = 30.00 less 24.00 credit.
    assert result.detail["Detroit local tax (unverified)"] == Decimal("24.00")
    assert result.detail["Grand Rapids (residence) (unverified)"] == Decimal("6.00")
    assert result.employee == Decimal("30.00")


def test_mi_credit_floors_at_zero():
    """Big work-city tax fully offsets a small residence-city tax."""
    result = _calc(work_locality="MI-DETROIT", residence_locality="MI-LANSING")
    # Detroit 24.00; Lansing resident 1.0% = 20.00 − 24.00 → floored at 0.
    assert result.employee == Decimal("24.00")
    assert "Lansing (residence) (unverified)" not in result.detail


# --- employer-side levies (synthetic rules) ---------------------------------


def test_employer_percent_levy():
    rule = _rule(employer_rate="0.005")
    # Exercise via LocalityRule directly is awkward — the engine reads the
    # registry — so pin the parsing here and the integration below.
    assert rule.employer_rate == Decimal("0.005")


def test_employer_flat_levy_parses():
    rule = _rule(employer_flat_per_year="48")
    assert rule.employer_flat_per_year == Decimal("48")


# --- integration with calculate_withholdings --------------------------------


def test_withholdings_include_local_tax_in_totals_and_net():
    from app.services.payroll_service import calculate_withholdings

    plain = calculate_withholdings(Decimal("2000"), work_state="PA")
    local = calculate_withholdings(
        Decimal("2000"), work_state="PA", work_locality="PA-PHILADELPHIA"
    )
    assert local["local_tax"] == Decimal("68.80")
    assert local["total_employee_tax"] - plain["total_employee_tax"] == Decimal("68.80")
    assert plain["net"] - local["net"] == Decimal("68.80")
    assert "Philadelphia local tax (unverified)" in local["detail"]


def test_withholdings_surface_unknown_localities():
    from app.services.payroll_service import calculate_withholdings

    result = calculate_withholdings(
        Decimal("2000"), work_state="PA", work_locality="PA-TYPO-VILLE"
    )
    assert result["unknown_localities"] == ["PA-TYPO-VILLE"]
    assert result["local_tax"] == 0


def test_withholdings_yonkers_surcharge_sees_state_tax():
    """percent_of_state_tax must receive the period's NY withholding."""
    from app.services.payroll_service import calculate_withholdings

    result = calculate_withholdings(
        Decimal("2000"),
        work_state="NY",
        work_locality="NY-YONKERS",
        residence_locality="NY-YONKERS",
    )
    assert result["state_income"] > 0
    expected = (result["state_income"] * Decimal("0.1675")).quantize(Decimal("0.01"))
    assert result["local_tax"] == expected


def test_withholdings_no_locality_is_unchanged():
    """Regression: employees without localities must be byte-identical."""
    from app.services.payroll_service import calculate_withholdings

    result = calculate_withholdings(Decimal("2000"), work_state="WA")
    assert result["local_tax"] == 0
    assert result["local_tax_employer"] == 0
    assert "local_tax_total" not in result["detail"]
