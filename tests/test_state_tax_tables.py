# ============================================================================
# Table-driven state withholding engine coverage.
# ----------------------------------------------------------------------------
# Two kinds of test live here:
#
#   1. Structural — every table parses, every state resolves to a real engine,
#      and a malformed table fails at load rather than mid-pay-run. These
#      guard the mechanism and should never need editing when a rate changes.
#   2. Arithmetic — hand-derived expected figures for a representative flat
#      state (IL), bracket state (VA), and premium state (NJ), so the math
#      itself is pinned. These DO change when a table is updated, which is the
#      point: an edited rate must be an intentional, reviewed edit.
#
# All wage figures assume a $2,000 biweekly check (26 periods) unless stated.
# ============================================================================

import json
from decimal import Decimal

import pytest

from app.services.state_tax import (
    GenericStateEngine,
    get_engine,
    suta_rate_for,
    supported_states,
)
from app.services.state_tax.table_engine import (
    StateTaxTableError,
    TableDrivenStateEngine,
    coverage_report,
    load_all_engines,
)

# The 50 states plus DC. If a table goes missing this list is what notices.
ALL_JURISDICTIONS = [
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
]

# States whose rules need a hand-written engine, so they have no JSON table.
DEDICATED = {"WA", "CA", "NY", "OR"}

NO_INCOME_TAX = {"AK", "FL", "NV", "NH", "SD", "TN", "TX", "WY", "WA"}


def _calc(engine, **overrides):
    """Run an engine with sensible defaults; override per-test."""
    kwargs = dict(
        gross=Decimal("2000"),
        taxable=Decimal("2000"),
        ytd_gross=Decimal("0"),
        pay_periods=26,
        hours=Decimal("80"),
        filing_status="single",
        wc_class_code=None,
    )
    kwargs.update(overrides)
    return engine.calculate(**kwargs)


def _table(**overrides):
    """A minimal valid table dict, overridable per-test."""
    table = {
        "state": "ZZ",
        "name": "Testland",
        "tax_year": 2026,
        "verified": True,
        "income_tax": {"method": "flat", "rate": "0.05"},
        "suta": {"wage_base": "10000", "default_rate": "0.02"},
    }
    table.update(overrides)
    return table


# --- structural -------------------------------------------------------------


def test_every_jurisdiction_resolves_to_a_real_engine():
    """No state should silently fall through to the zero-rate generic engine."""
    for code in ALL_JURISDICTIONS:
        engine = get_engine(code)
        assert not isinstance(
            engine, GenericStateEngine
        ), f"{code} fell back to generic"


def test_supported_states_covers_all_fifty_one():
    assert sorted(supported_states()) == sorted(ALL_JURISDICTIONS)


def test_dedicated_engines_win_over_tables():
    """WA/CA/NY/OR keep their hand-written engines even if a table appears."""
    for code in DEDICATED:
        assert not isinstance(get_engine(code), TableDrivenStateEngine)


def test_tables_exist_for_every_non_dedicated_state():
    tables = load_all_engines()
    expected = set(ALL_JURISDICTIONS) - DEDICATED
    assert set(tables) == expected


def test_unknown_code_still_falls_back_to_generic():
    for code in ("ZZ", "XX", "", None, "PR"):
        assert isinstance(get_engine(code), GenericStateEngine)


def test_get_engine_is_case_insensitive():
    assert get_engine("il") is get_engine("IL") is get_engine(" Il ")


def test_no_income_tax_states_withhold_nothing():
    for code in NO_INCOME_TAX:
        result = _calc(get_engine(code), gross=Decimal("5000"), taxable=Decimal("5000"))
        assert result.income_tax == 0, f"{code} withheld income tax"


def test_income_tax_states_actually_withhold():
    """The whole point of the change: these used to all return zero."""
    for code in set(ALL_JURISDICTIONS) - NO_INCOME_TAX:
        result = _calc(get_engine(code), gross=Decimal("4000"), taxable=Decimal("4000"))
        assert result.income_tax > 0, f"{code} withheld nothing on a $4,000 check"


def test_every_table_carries_provenance():
    """A table without a source URL cannot be verified by anyone later."""
    for row in coverage_report():
        assert row["source"].startswith("http"), f"{row['state']} has no source URL"
        assert row["tax_year"], f"{row['state']} has no tax_year"


def test_every_table_has_a_positive_suta_wage_base():
    for row in coverage_report():
        assert row["suta_wage_base"] > 0, f"{row['state']} has no SUTA wage base"


def test_nonpositive_wages_produce_empty_result():
    engine = get_engine("IL")
    assert _calc(engine, gross=Decimal("0")).income_tax == 0
    assert _calc(engine, taxable=Decimal("-5")).income_tax == 0


# --- table validation -------------------------------------------------------


def test_bad_state_code_rejected():
    with pytest.raises(StateTaxTableError, match="2-letter"):
        TableDrivenStateEngine(_table(state="ILL"))


def test_bad_method_rejected():
    with pytest.raises(StateTaxTableError, match="none/flat/brackets"):
        TableDrivenStateEngine(_table(income_tax={"method": "vibes"}))


def test_brackets_method_without_brackets_rejected():
    with pytest.raises(StateTaxTableError, match="none defined"):
        TableDrivenStateEngine(_table(income_tax={"method": "brackets"}))


def test_descending_brackets_rejected():
    bad = {"method": "brackets", "brackets": {"single": [["0", "0.02"], ["0", "0.03"]]}}
    with pytest.raises(StateTaxTableError, match="ascend"):
        TableDrivenStateEngine(_table(income_tax=bad))


def test_brackets_not_starting_at_zero_rejected():
    bad = {"method": "brackets", "brackets": {"single": [["100", "0.02"]]}}
    with pytest.raises(StateTaxTableError, match="must start at 0"):
        TableDrivenStateEngine(_table(income_tax=bad))


def test_malformed_bracket_row_rejected():
    bad = {"method": "brackets", "brackets": {"single": [["0", "0.02", "extra"]]}}
    with pytest.raises(StateTaxTableError, match="lower_bound, rate"):
        TableDrivenStateEngine(_table(income_tax=bad))


def test_premium_without_label_rejected():
    with pytest.raises(StateTaxTableError, match="missing a label"):
        TableDrivenStateEngine(_table(employee_other=[{"rate": "0.01"}]))


def test_committed_tables_are_valid_json_with_required_keys(tmp_path):
    """Guard the on-disk files, not just the parsed objects."""
    from app.services.state_tax.table_engine import TABLE_DIR

    for path in TABLE_DIR.glob("*.json"):
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        for key in (
            "state",
            "name",
            "tax_year",
            "verified",
            "source",
            "income_tax",
            "suta",
        ):
            assert key in raw, f"{path.name} is missing {key!r}"
        assert raw["state"] == path.stem, f"{path.name} disagrees with its filename"


# --- arithmetic: flat state (Illinois) --------------------------------------
# IL: 4.95% flat, $2,850 annual exemption (single).
# Annual taxable 2000 * 26 = 52,000; less 2,850 = 49,150.
# 49,150 * 0.0495 = 2,432.925 annual; / 26 = 93.5740... -> 93.57


def test_il_flat_rate_with_exemption():
    result = _calc(get_engine("IL"))
    assert result.income_tax == Decimal("93.57")


def test_il_married_exemption_is_double():
    single = _calc(get_engine("IL"), filing_status="single").income_tax
    married = _calc(get_engine("IL"), filing_status="married").income_tax
    # Married gets $5,700 vs $2,850 — an extra $2,850 sheltered at 4.95%/26.
    # Both figures are rounded to cents independently, so their difference can
    # sit a cent either side of the exact gap.
    expected_gap = Decimal("2850") * Decimal("0.0495") / 26
    assert abs((single - married) - expected_gap) <= Decimal("0.01")


def test_il_wage_under_exemption_yields_zero():
    result = _calc(get_engine("IL"), gross=Decimal("100"), taxable=Decimal("100"))
    assert result.income_tax == 0


# --- arithmetic: bracket state (Virginia) -----------------------------------
# VA brackets: 2% to 3,000; 3% to 5,000; 5% to 17,000; 5.75% above.
# Standard deduction 8,500 + exemption 930 = 9,430 sheltered.
# Annual 52,000 - 9,430 = 42,570 taxable.
#   3,000 @ 2%   =    60.00
#   2,000 @ 3%   =    60.00
#  12,000 @ 5%   =   600.00
#  25,570 @ 5.75%= 1,470.275
#                 ----------
#                  2,190.275 annual; / 26 = 84.2413... -> 84.24


def test_va_progressive_brackets():
    result = _calc(get_engine("VA"))
    assert result.income_tax == Decimal("84.24")


def test_va_top_bracket_is_open_ended():
    """A very large check must keep taxing at the top marginal rate."""
    low = _calc(get_engine("VA"), gross=Decimal("10000"), taxable=Decimal("10000"))
    high = _calc(get_engine("VA"), gross=Decimal("20000"), taxable=Decimal("20000"))
    assert high.income_tax > low.income_tax * 2


def test_unknown_filing_status_defaults_to_single():
    default = _calc(get_engine("VA"), filing_status="martian").income_tax
    single = _calc(get_engine("VA"), filing_status="single").income_tax
    assert default == single


def test_bracket_state_without_married_schedule_reuses_single():
    """VA publishes one schedule for all statuses — married must not 500."""
    assert _calc(get_engine("VA"), filing_status="married").income_tax > 0


# --- arithmetic: premiums (New Jersey) --------------------------------------
# NJ SDI 0.23% and FLI 0.09%, both capped at $165,400 of wages.


def test_nj_premiums_itemized_on_employee_side():
    result = _calc(get_engine("NJ"))
    assert result.detail["NJ SDI"] == Decimal("4.60")  # 2000 * 0.0023
    assert result.detail["NJ FLI"] == Decimal("1.80")  # 2000 * 0.0009
    assert result.employee_other == Decimal("6.40")


def test_nj_premiums_stop_at_the_wage_base():
    result = _calc(get_engine("NJ"), ytd_gross=Decimal("165400"))
    assert result.employee_other == 0


def test_nj_premium_prorates_across_the_wage_base():
    """Only the slice below the cap is premium-bearing."""
    result = _calc(get_engine("NJ"), ytd_gross=Decimal("164400"))
    # $1,000 of the $2,000 check remains under the $165,400 cap.
    assert result.detail["NJ SDI"] == Decimal("2.30")


def test_colorado_famli_splits_employee_and_employer():
    result = _calc(get_engine("CO"))
    assert result.detail["CO FAMLI (employee)"] == Decimal("9.00")
    assert result.detail["CO FAMLI (employer)"] == Decimal("9.00")
    assert result.employer_other == Decimal("9.00")


# --- verified flag / strict mode --------------------------------------------


def test_unverified_table_is_labelled_on_the_stub():
    result = _calc(get_engine("IL"))
    assert "IL income tax (unverified)" in result.detail


def test_strict_mode_suppresses_unverified_income_tax(monkeypatch):
    monkeypatch.setattr("app.config.PAYROLL_STRICT_TAX_TABLES", True)
    result = _calc(get_engine("IL"))
    assert result.income_tax == 0
    assert any("not applied" in key for key in result.detail)


def test_strict_mode_leaves_no_income_tax_states_alone(monkeypatch):
    """TX has no income tax at all — strict mode must not label it as skipped."""
    monkeypatch.setattr("app.config.PAYROLL_STRICT_TAX_TABLES", True)
    result = _calc(get_engine("TX"))
    assert result.income_tax == 0
    assert not any("not applied" in key for key in result.detail)


def test_strict_mode_still_collects_premiums(monkeypatch):
    """Strict mode is about unreviewed INCOME tax, not statutory premiums."""
    monkeypatch.setattr("app.config.PAYROLL_STRICT_TAX_TABLES", True)
    result = _calc(get_engine("NJ"))
    assert result.income_tax == 0
    assert result.employee_other > 0


def test_verified_table_is_not_labelled():
    engine = TableDrivenStateEngine(_table(state="IL", verified=True))
    result = _calc(engine)
    assert "IL income tax" in result.detail
    assert "IL income tax (unverified)" not in result.detail


# --- SUTA resolution --------------------------------------------------------


def test_suta_rate_prefers_configured_experience_rate():
    assert suta_rate_for("IL", {"IL": 0.041}) == Decimal("0.041")


def test_suta_rate_falls_back_to_state_new_employer_rate():
    assert suta_rate_for("IL", {}) == Decimal("0.0395")


def test_suta_rate_configured_lookup_is_case_insensitive():
    assert suta_rate_for("il", {"il": 0.033}) == Decimal("0.033")


def test_suta_rate_unknown_state_returns_none():
    assert suta_rate_for("ZZ", {}) is None
    assert suta_rate_for(None, {}) is None


def test_suta_wage_bases_differ_by_state():
    """The bug this fixes: one global rate/base applied to every state."""
    assert get_engine("IL").suta_wage_base != get_engine("MT").suta_wage_base


def test_suta_rate_tables_false_ignores_published_rate():
    assert suta_rate_for("IL", {}, tables=False) is None
    assert suta_rate_for("IL", {"IL": 0.041}, tables=False) == Decimal("0.041")


def test_resolve_suta_rate_explicit_beats_everything(monkeypatch):
    from app.services.payroll_service import resolve_suta_rate

    monkeypatch.setattr("app.config.SUTA_RATE_BY_STATE", {"IL": 0.05})
    assert resolve_suta_rate(Decimal("0.09"), "IL") == Decimal("0.09")


def test_resolve_suta_rate_prefers_configured_over_published(monkeypatch):
    from app.services.payroll_service import resolve_suta_rate

    monkeypatch.setattr("app.config.SUTA_RATE_BY_STATE", {"IL": 0.05})
    assert resolve_suta_rate(None, "IL") == Decimal("0.05")


def test_resolve_suta_rate_home_state_keeps_the_global_setting(monkeypatch):
    """Regression guard: an operator's own SUTA_RATE outranks a published
    new-employer rate for the state they actually operate in."""
    from app.services.payroll_service import resolve_suta_rate

    monkeypatch.setattr("app.config.EMPLOYER_STATE", "IL")
    monkeypatch.setattr("app.config.SUTA_RATE", 0.012)
    monkeypatch.setattr("app.config.SUTA_RATE_BY_STATE", {})
    assert resolve_suta_rate(None, "IL") == Decimal("0.012")


def test_resolve_suta_rate_other_state_uses_published_rate(monkeypatch):
    from app.services.payroll_service import resolve_suta_rate

    monkeypatch.setattr("app.config.EMPLOYER_STATE", "IL")
    monkeypatch.setattr("app.config.SUTA_RATE", 0.012)
    monkeypatch.setattr("app.config.SUTA_RATE_BY_STATE", {})
    assert resolve_suta_rate(None, "MT") == Decimal("0.0113")


def test_resolve_suta_rate_untabled_state_falls_back_to_global(monkeypatch):
    """WA/CA/NY/OR have engines but no table — they must still get a rate."""
    from app.services.payroll_service import resolve_suta_rate

    monkeypatch.setattr("app.config.EMPLOYER_STATE", "IL")
    monkeypatch.setattr("app.config.SUTA_RATE", 0.012)
    monkeypatch.setattr("app.config.SUTA_RATE_BY_STATE", {})
    assert resolve_suta_rate(None, "WA") == Decimal("0.012")


def test_config_parses_per_state_rate_list():
    from app.config import _parse_state_rates

    assert _parse_state_rates("WA:0.0121,OR:0.024") == {"WA": 0.0121, "OR": 0.024}
    # Whitespace and case are tolerated; malformed pairs are skipped, not fatal.
    assert _parse_state_rates(" il : 0.04 , garbage, ZZZ:0.01, MT:x") == {"IL": 0.04}
    assert _parse_state_rates("") == {}


def test_calculate_withholdings_uses_per_state_suta():
    """End-to-end: two states, same wages, different SUTA outcomes."""
    from app.services.payroll_service import calculate_withholdings

    il = calculate_withholdings(Decimal("3000"), work_state="IL")
    mt = calculate_withholdings(Decimal("3000"), work_state="MT")
    assert il["suta"] != mt["suta"]
