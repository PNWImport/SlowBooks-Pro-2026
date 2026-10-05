"""Banking route CRUD, reconciliation totals, and register boundaries."""

from datetime import date
from decimal import Decimal

from app.models.transactions import Transaction, TransactionLine


from tests.banking_helpers import (
    bank_account as _bank_account,
    bank_transaction as _bank_transaction,
)


def test_bank_account_and_transaction_crud(client, db_session):
    account = _bank_account(client)
    assert client.get(f"/api/banking/accounts/{account['id']}").status_code == 200
    changed = client.put(
        f"/api/banking/accounts/{account['id']}",
        json={"name": "Primary", "is_active": False},
    )
    assert changed.status_code == 200
    assert changed.json()["name"] == "Primary"
    assert client.get("/api/banking/accounts").json() == []
    assert client.get("/api/banking/accounts/999999").status_code == 404
    assert (
        client.put("/api/banking/accounts/999999", json={"name": "x"}).status_code
        == 404
    )

    active = _bank_account(client, "Savings")
    first = _bank_transaction(
        client,
        active["id"],
        "2026-09-01",
        "10.25",
        payee="Customer",
        description="Deposit",
        check_number="7",
    )
    _bank_transaction(client, active["id"], "2026-09-02", "-1.25")
    assert (
        client.post(
            "/api/banking/transactions",
            json={
                "bank_account_id": 999999,
                "date": "2026-09-01",
                "amount": 1,
                "category_account_id": 999999,
            },
        ).status_code
        == 404
    )
    # Imported statement rows are separate from posted register entries.
    from app.models.banking import BankTransaction

    assert (
        client.get(f"/api/banking/transactions?bank_account_id={active['id']}").json()
        == []
    )
    for day in (1, 2):
        db_session.add(
            BankTransaction(
                bank_account_id=active["id"],
                date=date(2026, 9, day),
                amount=1,
                match_status="unmatched",
            )
        )
    db_session.commit()
    rows = client.get(
        f"/api/banking/transactions?bank_account_id={active['id']}&skip=0&limit=1"
    ).json()
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-09-02"
    assert first["account_id"] == active["account_id"]


def test_reconciliation_lists_totals_and_error_paths(client):
    account = _bank_account(client)
    cleared = _bank_transaction(
        client,
        account["id"],
        "2026-09-01",
        "10.10",
        payee="P",
        description="D",
        check_number="8",
    )
    _bank_transaction(client, account["id"], "2026-09-02", "-2.05")
    response = client.post(
        "/api/banking/reconciliations",
        json={
            "bank_account_id": account["id"],
            "statement_date": "2026-09-30",
            "statement_balance": "10.10",
        },
    )
    assert response.status_code == 201, response.text
    reconciliation = response.json()
    base = f"/api/banking/reconciliations/{reconciliation['id']}"

    assert (
        client.post(f"{base}/toggle/{cleared['line_id']}").json()["reconciled"] is True
    )
    totals = client.get(f"{base}/transactions")
    assert totals.status_code == 200
    assert totals.json()["cleared_total"] == 10.1
    assert totals.json()["uncleared_total"] == -2.05
    assert totals.json()["difference"] == 0
    assert totals.json()["transactions"][0]["payee"] == "P"
    assert len(client.get("/api/banking/reconciliations").json()) == 1
    assert (
        len(
            client.get(
                f"/api/banking/reconciliations?account_id={account['account_id']}"
            ).json()
        )
        == 1
    )

    assert (
        client.get("/api/banking/reconciliations/999999/transactions").status_code
        == 404
    )
    assert (
        client.post("/api/banking/reconciliations/999999/toggle/1").status_code == 404
    )
    assert (
        client.post("/api/banking/reconciliations/999999/complete").status_code == 404
    )
    assert (
        client.post(
            "/api/banking/reconciliations",
            json={
                "bank_account_id": 999999,
                "statement_date": "2026-09-30",
                "statement_balance": 0,
            },
        ).status_code
        == 404
    )

    assert client.post(f"{base}/complete").status_code == 200
    # The account is reconciled through Sep 30: the next statement must be later.
    assert (
        client.post(
            "/api/banking/reconciliations",
            json={
                "bank_account_id": account["id"],
                "statement_date": "2026-09-30",
                "statement_balance": 999,
            },
        ).status_code
        == 400
    )
    mismatch = client.post(
        "/api/banking/reconciliations",
        json={
            "bank_account_id": account["id"],
            "statement_date": "2026-10-31",
            "statement_balance": 999,
        },
    ).json()
    assert (
        client.post(
            f"/api/banking/reconciliations/{mismatch['id']}/complete"
        ).status_code
        == 400
    )


def test_check_register_default_missing_and_account_errors(client):
    assert client.get("/api/banking/check-register").json() == {
        "account_id": None,
        "account_name": "",
        "entries": [],
    }
    assert (
        client.get("/api/banking/check-register?account_id=999999").status_code == 404
    )


def test_check_register_balances(client, db_session, seed_accounts):
    asset = seed_accounts["1000"]
    liability = seed_accounts["2000"]
    txn = Transaction(
        date=date(2026, 9, 1),
        description="Header",
        reference="REF",
        source_type="manual",
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add_all(
        [
            TransactionLine(
                transaction_id=txn.id,
                account_id=asset.id,
                debit=Decimal("25"),
                credit=Decimal("0"),
            ),
            TransactionLine(
                transaction_id=txn.id,
                account_id=liability.id,
                debit=Decimal("0"),
                credit=Decimal("25"),
                description="Line",
            ),
        ]
    )
    db_session.commit()

    default_register = client.get("/api/banking/check-register").json()
    assert default_register["account_id"] == asset.id
    expected = {
        "date": "2026-09-01",
        "description": "Header",
        "reference": "REF",
        "source_type": "manual",
        "payment": 0,
        "deposit": 25.0,
        "balance": 25.0,
    }
    assert {key: default_register["entries"][0][key] for key in expected} == expected
    assert default_register["entries"][0]["transaction_id"] == txn.id
    liability_register = client.get(
        f"/api/banking/check-register?account_id={liability.id}"
    ).json()
    assert liability_register["entries"][0]["payment"] == 25.0
    assert liability_register["entries"][0]["balance"] == 25.0
