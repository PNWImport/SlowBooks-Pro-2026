"""Budget upserts and variance signs against real synthetic journal entries."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.budgets import Budget
from app.services.accounting import create_journal_entry


def test_bulk_repeated_key_updates_one_row(authed_client, db_session, seed_accounts):
    item = {
        "account_id": seed_accounts["4000"].id,
        "year": 2026,
        "month": 1,
        "amount": "10",
    }
    response = authed_client.post(
        "/api/budgets/bulk", json=[item, {**item, "amount": "20"}]
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"saved": 2}
    db_session.expire_all()
    assert db_session.query(Budget).one().amount == Decimal("20")


def test_single_upsert_filters_and_variance(authed_client, db_session, seed_accounts):
    income, bank = seed_accounts["4000"], seed_accounts["1100"]
    item = {"account_id": income.id, "year": 2026, "month": 1, "amount": "10"}
    first = authed_client.post("/api/budgets", json=item)
    assert first.status_code == 201
    second = authed_client.post("/api/budgets", json={**item, "amount": "20"})
    assert second.status_code == 201 and second.json()["id"] == first.json()["id"]
    response = authed_client.post(
        "/api/budgets/bulk",
        json=[
            {**item, "amount": "30"},
            {**item, "account_id": bank.id, "amount": "15"},
        ],
    )
    assert response.status_code == 200
    assert len(authed_client.get("/api/budgets").json()) == 2
    assert (
        len(authed_client.get(f"/api/budgets?year=2026&account_id={income.id}").json())
        == 1
    )
    assert authed_client.get("/api/budgets?year=2025").json() == []
    for year in [2025, 2026]:
        create_journal_entry(
            db_session,
            date(year, 1, 15),
            "Synthetic sale",
            [
                {"account_id": bank.id, "debit": Decimal("12.34")},
                {"account_id": income.id, "credit": Decimal("12.34")},
            ],
        )
    db_session.commit()
    response = authed_client.get("/api/budgets/variance?year=2026")
    assert response.status_code == 200
    accounts = {row["account_id"]: row for row in response.json()["accounts"]}
    assert accounts[income.id]["months"][0] == {
        "month": 1,
        "budget": 30,
        "actual": 12.34,
        "variance": 17.66,
    }
    assert accounts[bank.id]["total_actual"] == 12.34
    assert len(accounts[income.id]["months"]) == 12
    assert authed_client.get("/api/budgets/variance?year=2024").json()["accounts"] == []


@pytest.mark.parametrize("month", [0, 13])
def test_invalid_month_rejected(authed_client, seed_accounts, month):
    response = authed_client.post(
        "/api/budgets",
        json={"account_id": seed_accounts["4000"].id, "year": 2026, "month": month},
    )
    assert response.status_code == 422
