from app.models.accounts import AccountType
from app.services import wave_import


def test_wave_keyword_type_mapping_and_blank_coa_rows():
    assert wave_import._map_type("custom payroll liability") is AccountType.LIABILITY
    accounts, errors = wave_import.parse_coa(
        "Account Name,Account Type\n,Income\nUnknown,Unmapped category\n"
    )
    assert accounts == []
    assert errors == ["COA row 3: unmapped Wave account type 'Unmapped category'"]


def test_wave_gl_skips_blank_rows_and_reports_invalid_cells():
    journals, errors = wave_import.parse_gl(
        "Transaction Date,Account Name,Debit Amount,Credit Amount\n"
        ",,,\n"
        "bad-date,Cash,not-money,\n"
    )
    assert journals == []
    assert len(errors) == 1
    assert "unparseable amount" in errors[0]


def test_wave_trial_balance_skips_headings_and_reports_invalid_amounts():
    balances, errors = wave_import.parse_tb(
        "Accounts,Debit,Credit\n" "Assets,,\n" "Total Assets,10,\n" "Cash,not-money,\n"
    )
    assert balances == {}
    assert len(errors) == 1
    assert "unparseable amount" in errors[0]
