"""Estimate conversion preserves terms and accounting dimensions."""

from datetime import date

from app.models.invoices import Invoice
from app.models.transactions import TransactionLine
from tests.test_job_costing import _code
from tests.test_jobs import _job


def test_estimate_conversion_preserves_due_date_job_and_cost_code(
    authed_client, db_session, seed_accounts, seed_customer
):
    job = _job(authed_client, seed_customer.id, "Converted project")
    cost = _code(authed_client, "09-01", "Converted labor", "labor")
    settings = authed_client.put(
        "/api/settings", json={"default_terms": "Due on receipt"}
    )
    assert settings.status_code == 200, settings.text
    created = authed_client.post(
        "/api/estimates",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-09-08",
            "job_id": job["id"],
            "lines": [
                {
                    "description": "Converted line",
                    "quantity": 1,
                    "rate": 100,
                    "job_id": job["id"],
                    "cost_code_id": cost["id"],
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    converted = authed_client.post(f"/api/estimates/{created.json()['id']}/convert")
    assert converted.status_code == 200, converted.text
    invoice = db_session.get(Invoice, converted.json()["id"])
    assert invoice.due_date == date(2026, 9, 8)
    assert invoice.job_id == job["id"]
    assert invoice.lines[0].job_id == job["id"]
    assert invoice.lines[0].cost_code_id == cost["id"]
    lines = (
        db_session.query(TransactionLine)
        .filter_by(transaction_id=invoice.transaction_id)
        .all()
    )
    income = next(line for line in lines if line.credit > 0)
    assert income.job_id == job["id"]
    assert income.cost_code_id == cost["id"]
    assert income.cost_type == "labor"
    repeated = authed_client.post(f"/api/estimates/{created.json()['id']}/convert")
    assert repeated.status_code == 400


def test_estimate_conversion_uses_item_income_skips_zero_and_posts_tax(
    authed_client, db_session, seed_accounts, seed_customer
):
    income = seed_accounts["4100"]
    item = authed_client.post(
        "/api/items",
        json={
            "name": "Mapped service",
            "item_type": "service",
            "rate": 100,
            "income_account_id": income.id,
        },
    )
    assert item.status_code == 201, item.text
    created = authed_client.post(
        "/api/estimates",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-09-08",
            "tax_rate": "0.10",
            "lines": [
                {"item_id": item.json()["id"], "quantity": 1, "rate": 100},
                {"description": "Zero", "quantity": 1, "rate": 0},
            ],
        },
    )
    assert created.status_code == 201, created.text
    converted = authed_client.post(f"/api/estimates/{created.json()['id']}/convert")
    assert converted.status_code == 200, converted.text
    invoice = db_session.get(Invoice, converted.json()["id"])
    lines = (
        db_session.query(TransactionLine)
        .filter_by(transaction_id=invoice.transaction_id)
        .all()
    )
    assert len(lines) == 3
    assert (
        next(line for line in lines if line.description == "").account_id == income.id
    )
    assert (
        sum(line.debit for line in lines) == sum(line.credit for line in lines) == 110
    )
