"""Core financial-report endpoint coverage with a synthetic balanced ledger."""

from datetime import date
from decimal import Decimal

from app.models.accounts import Account, AccountType
from app.models.transactions import Transaction, TransactionLine


def _ledger(db_session):
    accounts = [
        Account(
            name="Cash",
            account_number="1000",
            account_type=AccountType.ASSET,
            bank_kind="bank",
        ),
        Account(name="Revenue", account_number="4000", account_type=AccountType.INCOME),
        Account(
            name="Supplies", account_number="5000", account_type=AccountType.EXPENSE
        ),
        Account(
            name="Payable", account_number="2000", account_type=AccountType.LIABILITY
        ),
    ]
    db_session.add_all(accounts)
    db_session.flush()
    txn = Transaction(
        date=date(2026, 5, 1),
        description="Sale",
        reference="R-1",
        source_type="payment",
        source_id=7,
    )
    txn.lines = [
        TransactionLine(
            account_id=accounts[0].id,
            debit=Decimal("100"),
            credit=0,
            description="Cash line",
        ),
        TransactionLine(account_id=accounts[1].id, debit=0, credit=Decimal("100")),
    ]
    txn2 = Transaction(date=date(2026, 5, 2), description="Supplies")
    txn2.lines = [
        TransactionLine(account_id=accounts[2].id, debit=Decimal("20"), credit=0),
        TransactionLine(account_id=accounts[3].id, debit=0, credit=Decimal("20")),
    ]
    db_session.add_all([txn, txn2])
    for source_type, source_id in (
        ("bill", 8),
        ("bill_payment", 9),
        ("manual_journal", 10),
    ):
        extra = Transaction(
            date=date(2026, 5, 3), source_type=source_type, source_id=source_id
        )
        extra.lines = [
            TransactionLine(account_id=accounts[0].id, debit=Decimal("1"), credit=0),
            TransactionLine(account_id=accounts[1].id, debit=0, credit=Decimal("1")),
        ]
        db_session.add(extra)
    db_session.commit()
    return accounts


def test_general_ledger_trial_balance_and_cash_flow_defaults(client, db_session):
    accounts = _ledger(db_session)
    ledger = client.get("/api/reports/general-ledger?account_id=%s" % accounts[0].id)
    assert ledger.status_code == 200
    assert ledger.json()["accounts"][0]["entries"][0]["reference"] == "R-1"
    trial = client.get("/api/reports/trial-balance")
    assert trial.status_code == 200
    assert trial.json()["total_debit"] == trial.json()["total_credit"] == 123.0
    cash = client.get("/api/reports/cash-flow")
    assert cash.status_code == 200
    body = cash.json()
    assert body["total_investing"] == 0.0
    assert body["total_operating"] == 103.0
    assert body["net_change"] == 103.0


def test_general_ledger_empty_filter_and_source_links(client, db_session):
    accounts = _ledger(db_session)
    empty = client.get(
        "/api/reports/general-ledger?start_date=2020-01-01&end_date=2020-12-31"
    )
    assert empty.json()["accounts"] == []
    detail = client.get(
        f"/api/reports/account-transactions?account_id={accounts[0].id}"
    ).json()
    assert detail["entries"][0]["source_link"] == "/#/payments/7"
    assert client.get("/api/reports/profit-loss-by-class").status_code == 200
    assert client.get("/api/reports/job-profitability").status_code == 200


def test_pdf_sections_render_cogs_and_balance_rows():
    from app.routes.reports.financial import _bs_section, _pl_section

    pl = _pl_section(
        {
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "income": [],
            "cogs": [{"account_name": "Materials", "amount": 5}],
            "expenses": [],
            "total_income": 0,
            "total_cogs": 5,
            "gross_profit": -5,
            "total_expenses": 0,
            "net_income": -5,
        }
    )
    assert any("Materials" in row["cells"][0] for row in pl["rows"])
    bs = _bs_section(
        {
            "as_of_date": "2026-12-31",
            "assets": [{"account_name": "Cash", "amount": 1}],
            "liabilities": [],
            "equity": [],
            "total_assets": 1,
            "total_liabilities": 0,
            "total_equity": 0,
        }
    )
    assert any("Cash" in row["cells"][0] for row in bs["rows"])


def test_profit_loss_by_class_includes_cogs_bucket(client, db_session):
    from app.models.classes import TxnClass

    cogs = Account(
        name="Class COGS", account_number="5999", account_type=AccountType.COGS
    )
    cls = TxnClass(name="Materials Class")
    db_session.add_all([cogs, cls])
    db_session.flush()
    txn = Transaction(date=date(2026, 6, 1), description="COGS")
    txn.lines = [
        TransactionLine(
            account_id=cogs.id, debit=Decimal("5"), credit=0, class_id=cls.id
        )
    ]
    db_session.add(txn)
    db_session.commit()
    response = client.get(
        "/api/reports/profit-loss-by-class?start_date=2026-01-01&end_date=2026-12-31"
    )
    assert response.status_code == 200
    row = next(
        item
        for item in response.json()["classes"]
        if item["class_name"] == "Materials Class"
    )
    assert row["cogs"] == 5.0
