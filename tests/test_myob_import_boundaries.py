from app.services import myob_import


def test_myob_classifier_and_empty_code_map_fallbacks():
    assert myob_import.classify_filename("notes.txt") is None
    assert myob_import._code_to_name_map(None) == {}


def test_myob_coa_skips_blank_rows_and_reports_unknown_types():
    accounts, errors = myob_import.parse_coa(
        "Account Name,Account Type\n,Asset\nMystery,Unknown type\n"
    )
    assert accounts == []
    assert errors == ["COA row 3: unmapped MYOB account type 'unknown type'"]


def test_myob_gl_skips_blanks_and_reports_invalid_values():
    parse_gl = myob_import.make_parse_gl(None)
    journals, errors = parse_gl(
        "Date,Account Name,Debit Amount,Credit Amount\n" ",,,\n" "not-a-date,Cash,1,\n"
    )
    assert journals == []
    assert len(errors) == 1
    assert "unparseable date" in errors[0]


def test_myob_trial_balance_skips_totals_and_reports_bad_amounts():
    balances, errors = myob_import.parse_tb(
        "Account Name,YTD Debit,YTD Credit\n" "Grand Total:,1,\n" "Cash,not-money,\n"
    )
    assert balances == {}
    assert len(errors) == 1
    assert "unparseable amount" in errors[0]
