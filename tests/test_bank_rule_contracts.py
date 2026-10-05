"""Bank-rule CRUD and priority matching against synthetic transactions."""

from datetime import date

import pytest

from app.models.bank_rules import BankRule
from app.models.banking import BankAccount, BankTransaction


def test_crud_ordering_and_missing_rules(authed_client):
    first = authed_client.post(
        "/api/bank-rules", json={"name": "Low", "pattern": "low", "priority": 1}
    )
    second = authed_client.post(
        "/api/bank-rules", json={"name": "High", "pattern": "high", "priority": 2}
    )
    assert first.status_code == second.status_code == 201
    key = first.json()["id"]
    assert authed_client.get(f"/api/bank-rules/{key}").json()["name"] == "Low"
    assert [r["name"] for r in authed_client.get("/api/bank-rules").json()] == [
        "High",
        "Low",
    ]
    changed = authed_client.put(
        f"/api/bank-rules/{key}", json={"priority": 3, "is_active": False}
    )
    assert changed.status_code == 200 and changed.json()["pattern"] == "low"
    assert changed.json()["is_active"] is False
    assert authed_client.delete(f"/api/bank-rules/{key}").json() == {
        "status": "deleted"
    }
    assert authed_client.get(f"/api/bank-rules/{key}").status_code == 404
    assert (
        authed_client.put(
            f"/api/bank-rules/{key}", json={"name": "Missing"}
        ).status_code
        == 404
    )
    assert authed_client.delete(f"/api/bank-rules/{key}").status_code == 404


@pytest.mark.parametrize(
    "kind,pattern,payee",
    [
        ("contains", "SHOP", "Synthetic Shop"),
        ("starts_with", "SYN", "Synthetic Shop"),
        ("exact", "SYNTHETIC SHOP", "Synthetic Shop"),
    ],
)
def test_match_priority_preserves_manual_and_repeat_idempotence(
    authed_client, db_session, seed_accounts, kind, pattern, payee
):
    bank = BankAccount(name="Synthetic bank")
    db_session.add(bank)
    db_session.flush()
    chosen = seed_accounts["1100"].id
    fallback = seed_accounts["4000"].id
    db_session.add_all(
        [
            BankRule(
                name="Chosen",
                pattern=pattern,
                rule_type=kind,
                priority=10,
                account_id=chosen,
            ),
            BankRule(
                name="Fallback",
                pattern="shop",
                rule_type="contains",
                priority=0,
                account_id=fallback,
            ),
            BankRule(
                name="Inactive",
                pattern=pattern,
                priority=100,
                is_active=False,
                account_id=fallback,
            ),
        ]
    )
    txns = [
        BankTransaction(
            bank_account_id=bank.id,
            date=date(2026, 1, 1),
            amount=-10,
            payee=name,
            match_status=status,
            category_account_id=fallback if status == "manual" else None,
        )
        for name, status in [
            (payee, "unmatched"),
            (payee, "manual"),
            (None, "unmatched"),
            ("Unrelated", "unmatched"),
        ]
    ]
    db_session.add_all(txns)
    db_session.commit()
    response = authed_client.post("/api/bank-rules/apply")
    assert response.status_code == 200, response.text
    assert response.json() == {"matched": 1, "total_unmatched": 3}
    db_session.expire_all()
    assert txns[0].category_account_id == chosen and txns[0].match_status == "unmatched"
    assert txns[0].transaction_line_id is None  # a category is not a posting
    assert txns[1].category_account_id == fallback and txns[1].match_status == "manual"
    assert txns[2].match_status == txns[3].match_status == "unmatched"
    assert authed_client.post("/api/bank-rules/apply").json() == {
        "matched": 0,
        "total_unmatched": 3,
    }
