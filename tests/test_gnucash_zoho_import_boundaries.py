import pytest

from app.services import gnucash_import, zoho_import


@pytest.mark.parametrize(
    "service,label",
    [(gnucash_import, "GnuCash"), (zoho_import, "Zoho")],
)
def test_import_parsers_handle_blank_and_malformed_rows(service, label):
    accounts, coa_errors = service.parse_coa(
        "Account Name,Type\n,Asset\nMystery,Unknown type\n"
    )
    assert accounts == []
    assert coa_errors == [f"COA row 3: unmapped {label} account type 'unknown type'"]

    journals, gl_errors = service.parse_gl(
        "Date,Account Name,Amount,Debit,Credit\n"
        ",,,,\n"
        "not-a-date,Cash,not-money,not-money,\n"
    )
    assert journals == []
    assert len(gl_errors) == 1

    balances, tb_errors = service.parse_tb(
        "Account Name,Debit,Credit\n" ",1,\n" "Cash,not-money,\n"
    )
    assert balances == {}
    assert len(tb_errors) == 1
    assert "unparseable amount" in tb_errors[0]

    balances, errors = service.parse_tb(
        "Account Name,Debit,Credit\nCash,10,2\nCash,1,\n"
    )
    assert balances == {"cash": 9}
    assert errors == []


@pytest.mark.parametrize("service", [gnucash_import, zoho_import])
def test_adapter_dry_run_wrapper_reports_missing_bundle(service, db_session):
    result = service.dry_run(db_session, {})
    assert result["ok"] is False
    assert len(result["errors"]) == 2


def test_gnucash_skips_root_and_placeholder_accounts():
    accounts, errors = gnucash_import.parse_coa(
        "Account Name,Type,Placeholder\n" "Root,ROOT,\n" "Assets,ASSET,true\n"
    )
    assert accounts == []
    assert errors == []
