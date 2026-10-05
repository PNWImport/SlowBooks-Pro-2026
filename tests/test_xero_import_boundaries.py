from app.services import xero_import


def test_xero_classifier_and_coa_reject_unknown_or_blank_rows():
    assert xero_import.classify_filename("notes.txt") is None
    accounts, errors = xero_import.parse_coa("Name,Type\n,Bank\nMystery,Unknown type\n")
    assert accounts == []
    assert errors == ["COA row 3: unmapped Xero account type 'unknown type'"]


def test_xero_gl_skips_blank_rows_and_reports_invalid_dates():
    journals, errors = xero_import.parse_gl(
        "Journal Number,Date,Account,Debit,Credit\n" ",,,,\n" "1,not-a-date,Cash,1,\n"
    )
    assert journals == []
    assert len(errors) == 1
    assert "unparseable date" in errors[0]


def test_xero_trial_balance_skips_blank_names_and_reports_bad_amounts():
    balances, errors = xero_import.parse_tb(
        "Account,Debit,Credit\n" ",1,\n" "Cash,not-money,\n"
    )
    assert balances == {}
    assert len(errors) == 1
    assert "unparseable amount" in errors[0]
