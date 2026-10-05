"""CSV bank import: format auto-detection, PayPal Gross/Fee handling,
content-derived import_id dedup, and bank-rule parity with OFX import."""

from decimal import Decimal
from pathlib import Path

from app.models.accounts import Account, AccountType
from app.models.bank_rules import BankRule
from app.models.banking import BankAccount, BankTransaction
from app.services.bank_csv_import import (
    detect_format,
    import_csv_transactions,
    parse_csv,
)

CHASE_CHECKING_CSV = (
    "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
    "DEBIT,07/01/2026,COFFEE SHOP,-4.50,DEBIT_CARD,995.50,\n"
    "DEBIT,07/01/2026,COFFEE SHOP,-4.50,DEBIT_CARD,991.00,\n"
    "CREDIT,07/02/2026,PAYROLL DEPOSIT,2500.00,ACH_CREDIT,3491.00,\n"
    "DEBIT,07/03/2026,CHECK 1041,-125.00,CHECK_PAID,3366.00,1041\n"
)

CHASE_CREDIT_CSV = (
    "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
    "07/05/2026,07/06/2026,HARDWARE STORE,Home,Sale,-89.99,\n"
    "07/07/2026,07/08/2026,PAYMENT THANK YOU,,Payment,500.00,\n"
)

PAYPAL_OLD_CSV = (
    '﻿"Date","Time","Time Zone","Name","Type","Status","Currency","Gross","Fee","Net",'
    '"From Email Address","To Email Address","Transaction ID","Item Title"\n'
    '"07/10/2026","10:00:00","PDT","Ada Lovelace","Express Checkout Payment","Completed",'
    '"USD","100.00","-3.20","96.80","ada@example.com","me@example.com","TX123","Widget"\n'
    '"07/10/2026","10:00:05","PDT","","Bank Deposit to PP Account","Completed",'
    '"USD","-96.80","0.00","-96.80","","","TX124",""\n'
)

PAYPAL_NEW_CSV = (
    "Date,Time,Time Zone,Description,Currency,Gross,Fee,Net,Balance,Transaction ID,"
    "From Email Address,Name,Bank Name,Bank Account,Shipping and Handling Amount,"
    "Sales Tax,Invoice ID,Reference Txn ID\n"
    "07/12/2026,09:00:00,PDT,General Payment,USD,250.00,-7.55,242.45,242.45,TX200,"
    "grace@example.com,Grace Hopper,,,0.00,0.00,INV-9,\n"
)

BOFA_DETAIL_FIXTURE = Path(__file__).parent / "fixtures/bofa_detail_real_shape.csv"
BOFA_DETAIL_CSV_BYTES = BOFA_DETAIL_FIXTURE.read_bytes()
BOFA_DETAIL_CSV = BOFA_DETAIL_CSV_BYTES.decode("ascii")


def _mk_bank_account(db_session):
    ba = BankAccount(name="Test Checking", bank_name="Chase")
    db_session.add(ba)
    db_session.commit()
    return ba


# ── Format detection ─────────────────────────────────────────────────────


def test_detect_formats():
    assert (
        detect_format(
            {"Details", "Posting Date", "Description", "Amount", "Type", "Balance"}
        )
        == "chase_checking"
    )
    assert (
        detect_format(
            {
                "Transaction Date",
                "Post Date",
                "Description",
                "Category",
                "Type",
                "Amount",
            }
        )
        == "chase_credit"
    )
    assert detect_format({"Date", "Time", "Name", "Type", "Status"}) == "paypal"
    assert (
        detect_format({"Date", "Description", "Amount", "Running Bal."})
        == "bofa_detail"
    )
    assert detect_format({"Nothing", "Useful"}) == "unknown"


def test_parse_chase_checking_rows():
    result = parse_csv(CHASE_CHECKING_CSV)
    assert result["format"] == "chase_checking"
    assert result["error"] is None
    txns = result["transactions"]
    assert len(txns) == 4
    assert txns[0]["amount"] == Decimal("-4.50")
    assert txns[3]["check_number"] == "1041"


def test_parse_paypal_gross_fee_and_mirror_skip():
    result = parse_csv(PAYPAL_OLD_CSV)
    assert result["format"] == "paypal"
    txns = result["transactions"]
    # The "Bank Deposit to PP Account" mirror row is skipped
    assert len(txns) == 1
    # Gross, NOT Net
    assert txns[0]["amount"] == Decimal("100.00")
    assert txns[0]["fee"] == Decimal("-3.20")


def test_parse_paypal_new_format():
    result = parse_csv(PAYPAL_NEW_CSV)
    assert result["format"] == "paypal_new"
    txns = result["transactions"]
    assert len(txns) == 1
    assert txns[0]["amount"] == Decimal("250.00")
    assert txns[0]["payee"] == "Grace Hopper"


def test_parse_bofa_detail_after_summary_preamble():
    # The fixture preserves the line endings emitted by both real exports.
    assert b"\r\n" in BOFA_DETAIL_CSV_BYTES
    assert b"\n" not in BOFA_DETAIL_CSV_BYTES.replace(b"\r\n", b"")

    result = parse_csv(BOFA_DETAIL_CSV)
    assert result["format"] == "bofa_detail"
    assert result["error"] is None
    txns = result["transactions"]
    assert len(txns) == 2
    assert txns[0]["payee"] == "SYNTHETIC PAYOR, LLC CREDIT"
    assert txns[0]["amount"] == Decimal("1250.00")
    assert txns[1]["amount"] == Decimal("-250.00")


# ── Import + dedup ───────────────────────────────────────────────────────


def test_same_day_same_amount_duplicates_both_import(db_session):
    """Two identical coffee charges on the same day are BOTH real
    transactions — the (date, amount) dedup this replaces dropped one."""
    ba = _mk_bank_account(db_session)
    result = import_csv_transactions(db_session, ba.id, CHASE_CHECKING_CSV)
    assert result["imported"] == 4
    assert result["skipped"] == 0
    coffee = (
        db_session.query(BankTransaction)
        .filter(BankTransaction.payee == "COFFEE SHOP")
        .all()
    )
    assert len(coffee) == 2


def test_reimport_same_file_skips_everything(db_session):
    ba = _mk_bank_account(db_session)
    first = import_csv_transactions(db_session, ba.id, CHASE_CHECKING_CSV)
    assert first["imported"] == 4
    second = import_csv_transactions(db_session, ba.id, CHASE_CHECKING_CSV)
    assert second["imported"] == 0
    assert second["skipped"] == 4


def test_bofa_reimport_skips_everything(db_session):
    ba = _mk_bank_account(db_session)
    first = import_csv_transactions(db_session, ba.id, BOFA_DETAIL_CSV)
    assert first["format"] == "bofa_detail"
    assert first["imported"] == 2
    assert first["matched"] == 0

    rows = (
        db_session.query(BankTransaction)
        .filter(BankTransaction.bank_account_id == ba.id)
        .all()
    )
    assert len(rows) == 2
    assert all(row.import_source == "csv_bofa_detail" for row in rows)

    second = import_csv_transactions(db_session, ba.id, BOFA_DETAIL_CSV)
    assert second["imported"] == 0
    assert second["skipped"] == 2


def test_overlapping_export_skips_only_known_rows(db_session):
    """A later export containing already-imported rows plus new ones
    imports only the new ones."""
    ba = _mk_bank_account(db_session)
    import_csv_transactions(db_session, ba.id, CHASE_CHECKING_CSV)

    overlapping = CHASE_CHECKING_CSV + (
        "DEBIT,07/04/2026,GROCERY STORE,-62.10,DEBIT_CARD,3303.90,\n"
    )
    result = import_csv_transactions(db_session, ba.id, overlapping)
    assert result["imported"] == 1
    assert result["skipped"] == 4


def test_import_source_tagged_with_format(db_session):
    ba = _mk_bank_account(db_session)
    import_csv_transactions(db_session, ba.id, CHASE_CREDIT_CSV)
    sources = {
        t.import_source
        for t in db_session.query(BankTransaction)
        .filter(BankTransaction.bank_account_id == ba.id)
        .all()
    }
    assert sources == {"csv_chase_credit"}


def test_paypal_fee_surfaces_in_description(db_session):
    ba = _mk_bank_account(db_session)
    import_csv_transactions(db_session, ba.id, PAYPAL_OLD_CSV)
    txn = (
        db_session.query(BankTransaction)
        .filter(BankTransaction.bank_account_id == ba.id)
        .one()
    )
    assert "fee -3.20" in txn.description


# ── Bank-rule parity with OFX ────────────────────────────────────────────


def test_bank_rules_auto_apply_on_csv_import(db_session):
    ba = _mk_bank_account(db_session)
    expense = Account(name="Meals", account_type=AccountType.EXPENSE)
    db_session.add(expense)
    db_session.commit()
    db_session.add(
        BankRule(
            name="Coffee",
            pattern="coffee",
            rule_type="contains",
            account_id=expense.id,
        )
    )
    db_session.commit()

    import_csv_transactions(db_session, ba.id, CHASE_CHECKING_CSV)
    coffee = (
        db_session.query(BankTransaction)
        .filter(BankTransaction.payee == "COFFEE SHOP")
        .all()
    )
    assert all(t.match_status == "unmatched" for t in coffee)  # categorised, not posted
    assert all(t.category_account_id == expense.id for t in coffee)


def test_unknown_format_reports_error(db_session):
    ba = _mk_bank_account(db_session)
    result = import_csv_transactions(db_session, ba.id, "Foo,Bar\n1,2\n")
    assert result["imported"] == 0
    assert result["errors"]


# ── Bank of America: shapes the contributor's tests did not reach ────────
#
# The BofA parser arrived with the preamble case covered (PR #130). These
# are the cases around it: the same export without a preamble, the metadata
# row that carries an amount, the scan bound, and — the one that matters —
# what the ledger does when one of these rows is added from the queue.

BOFA_NO_PREAMBLE_CSV = (
    "Date,Description,Amount,Running Bal.\n"
    '01/20/2026,Interest Earned,4.90,"1,004.90"\n'
    '01/22/2026,Online Banking transfer to CHK 1234,-250.00,"754.90"\n'
)

BOFA_METADATA_WITH_AMOUNT_CSV = (
    "Date,Description,Amount,Running Bal.\n"
    '01/01/2026,Beginning balance as of 01/01/2026,1000.00,"1,000.00"\n'
    '01/20/2026,Interest Earned,4.90,"1,004.90"\n'
    '01/31/2026,Ending balance as of 01/31/2026,1004.90,"1,004.90"\n'
)


def test_bofa_export_without_the_summary_preamble():
    """BofA emits this export both ways. The header-scan must not require
    a preamble to be there."""
    result = parse_csv(BOFA_NO_PREAMBLE_CSV)
    assert result["format"] == "bofa_detail"
    assert [t["amount"] for t in result["transactions"]] == [
        Decimal("4.90"),
        Decimal("-250.00"),
    ]


def test_bofa_minus_sign_and_parentheses_are_the_same_debit():
    """The summary block uses (250.00) and the detail rows use -250.00.
    Both are money leaving the account."""
    paren = parse_csv(
        "Date,Description,Amount,Running Bal.\n"
        '01/22/2026,Transfer out,(250.00),"754.90"\n'
    )["transactions"]
    minus = parse_csv(BOFA_NO_PREAMBLE_CSV)["transactions"]
    assert paren[0]["amount"] == minus[1]["amount"] == Decimal("-250.00")


def test_bofa_balance_rows_are_dropped_even_when_they_carry_an_amount():
    """A beginning-balance row is the statement's opening figure, not a
    deposit. BofA normally leaves its Amount blank, which the blank guard
    catches; if it ever fills it in, importing it would overstate the
    account by the whole opening balance and the register would show a
    deposit nobody made."""
    txns = parse_csv(BOFA_METADATA_WITH_AMOUNT_CSV)["transactions"]
    assert [t["description"] for t in txns] == ["Interest Earned"]


def test_header_scan_is_bounded_so_a_data_row_cannot_be_taken_for_a_header():
    """The scan exists for BofA's ~8-line preamble. Past the bound the file
    is data, and a data row that happens to spell a signature's column
    names would truncate the import at that row."""
    from app.services.bank_csv_import import PREAMBLE_SCAN_LINES

    padding = "junk,junk2\n" * (PREAMBLE_SCAN_LINES + 5)
    result = parse_csv(padding + "Date,Description,Amount,Running Bal.\n")
    assert result["format"] == "unknown"

    near = "junk,junk2\n" * (PREAMBLE_SCAN_LINES - 2)
    assert parse_csv(near + "Date,Description,Amount,Running Bal.\n")["format"] == (
        "bofa_detail"
    )


def test_bofa_row_added_from_the_queue_posts_the_right_way_round(
    client, db_session, seed_accounts
):
    """The sign contract, end to end, through the review queue.

    Everything above tests the parser in isolation. This is the test that
    would have caught a sign inversion: a positive BofA row must DEBIT the
    bank account (money in) and a negative one must CREDIT it. #119 is why
    a parser test is not enough — the question is always what reached the
    ledger."""
    from app.models.transactions import TransactionLine

    checking = seed_accounts["1000"]
    feed = client.post(
        "/api/banking/accounts",
        json={"name": "BofA checking", "account_id": checking.id},
    ).json()

    out = import_csv_transactions(db_session, feed["id"], BOFA_NO_PREAMBLE_CSV)
    assert out["imported"] == 2 and out["format"] == "bofa_detail"

    rows = client.get(f"/api/banking/transactions?bank_account_id={feed['id']}").json()
    by_amount = {Decimal(str(r["amount"])): r for r in rows}

    def add(row, category):
        r = client.post(
            f"/api/banking/transactions/{row['id']}/add",
            json={"category_account_id": category.id},
        )
        assert r.status_code in (200, 201), r.text
        return r.json()

    # +4.90 interest earned: money in, so the bank account is debited.
    add(by_amount[Decimal("4.90")], seed_accounts["4000"])
    # -250.00 transfer out: money out, so the bank account is credited.
    add(by_amount[Decimal("-250.00")], seed_accounts["6000"])

    lines = (
        db_session.query(TransactionLine)
        .filter(TransactionLine.account_id == checking.id)
        .all()
    )
    debits = sum(line.debit or 0 for line in lines)
    credits = sum(line.credit or 0 for line in lines)
    assert debits == Decimal("4.90")
    assert credits == Decimal("250.00")

    reg = client.get(f"/api/banking/check-register?account_id={checking.id}").json()
    assert reg["entries"][-1]["balance"] == "-245.10" or Decimal(
        str(reg["entries"][-1]["balance"])
    ) == Decimal("-245.10")
