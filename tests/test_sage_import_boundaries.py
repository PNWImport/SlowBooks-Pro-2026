from app.services import sage_import


def test_sage_coa_handles_blank_and_unknown_rows():
    accounts, errors = sage_import.parse_coa(
        "Account ID,Account Description,Account Type\n"
        "1,,Cash\n"
        "2,Mystery,Unknown type\n"
    )
    assert accounts == []
    assert errors == ["COA row 3: unmapped Sage account type 'unknown type'"]


def test_sage_gl_handles_blank_unknown_and_malformed_rows():
    parse_gl = sage_import.make_parse_gl(None)
    journals, errors = parse_gl(
        "Date,Account ID,Account Description,Debit Amt,Credit Amt\n"
        ",,,,\n"
        "2026-01-01,999,,1,\n"
        "not-a-date,1,Cash,1,\n"
    )
    assert journals == []
    assert len(errors) == 2
    assert "not found" in errors[0]
    assert "unparseable date" in errors[1]


def test_sage_trial_balance_handles_blank_bad_and_valid_rows():
    balances, errors = sage_import.parse_tb(
        "Account Description,Debit Amt,Credit Amt\n"
        ",1,\n"
        "Broken,not-money,\n"
        "Cash,10,2\n"
        "Cash,1,\n"
    )
    assert balances == {"cash": 9}
    assert len(errors) == 1
    assert "unparseable amount" in errors[0]


def test_sage_dry_run_wrapper_reports_missing_bundle(db_session):
    result = sage_import.dry_run(db_session, {})
    assert result["ok"] is False
    assert len(result["errors"]) == 2
