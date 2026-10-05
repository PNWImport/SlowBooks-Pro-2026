"""Bank reconciliation ownership, state, and row-lock regressions."""

from sqlalchemy.orm import Query


from tests.banking_helpers import (
    bank_account as _account,
    bank_transaction as _transaction,
)


def test_reconciliation_scopes_transactions_and_locks_transitions(client, monkeypatch):
    locked_entities = []
    original = Query.with_for_update

    def spy(query, *args, **kwargs):
        entity = (
            query.column_descriptions[0].get("entity")
            if query.column_descriptions
            else None
        )
        if entity is not None:
            locked_entities.append(entity.__name__)
        return original(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", spy)

    primary = _account(client, "Operating")
    other = _account(client, "Savings")
    owned = _transaction(client, primary["id"], "2026-09-01", 100)
    foreign = _transaction(client, other["id"], "2026-09-01", 100)
    future = _transaction(client, primary["id"], "2026-10-01", 100)
    reconciliation = client.post(
        "/api/banking/reconciliations",
        json={
            "bank_account_id": primary["id"],
            "statement_date": "2026-09-30",
            "statement_balance": 100,
        },
    ).json()
    base = f"/api/banking/reconciliations/{reconciliation['id']}"

    assert client.post(f"{base}/toggle/{foreign['line_id']}").status_code == 400
    assert client.post(f"{base}/toggle/{future['line_id']}").status_code == 400
    toggled = client.post(f"{base}/toggle/{owned['line_id']}")
    assert toggled.status_code == 200
    assert toggled.json()["reconciled"] is True

    completed = client.post(f"{base}/complete")
    assert completed.status_code == 200, completed.text
    assert client.post(f"{base}/complete").status_code == 400
    assert client.post(f"{base}/toggle/{owned['line_id']}").status_code == 400
    assert {"BankAccount", "TransactionLine", "Reconciliation"}.issubset(
        locked_entities
    )
