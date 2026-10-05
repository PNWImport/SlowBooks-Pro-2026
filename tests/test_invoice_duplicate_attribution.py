"""Duplicated invoices retain header defaults and line job/class overrides."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.invoices import Invoice
from app.models.cost_codes import CostCode
from app.models.transactions import Transaction, TransactionLine
from tests.test_jobs import _job
from tests.test_invoice_posting import _create_invoice


def test_duplicate_preserves_line_tax_and_cost_code(
    authed_client, db_session, seed_accounts, seed_customer
):
    original = _create_invoice(authed_client, seed_customer.id)
    cost = CostCode(code="SYN", name="Synthetic cost", cost_type="labor")
    db_session.add(cost)
    db_session.flush()
    source = db_session.get(Invoice, original["id"])
    source.lines[0].cost_code_id = cost.id
    source.lines[0].is_taxable = False
    db_session.commit()
    result = authed_client.post(f"/api/invoices/{original['id']}/duplicate")
    assert result.status_code == 201, result.text
    duplicate = db_session.get(Invoice, result.json()["id"])
    assert duplicate.lines[0].cost_code_id == cost.id
    assert duplicate.lines[0].is_taxable is False
    posted = (
        db_session.query(TransactionLine)
        .filter_by(transaction_id=duplicate.transaction_id)
        .all()
    )
    income_line = next(line for line in posted if line.credit > 0)
    assert income_line.cost_code_id == cost.id
    assert income_line.cost_type == "labor"


def test_duplicate_uses_item_income_and_skips_zero_line(
    authed_client, db_session, seed_accounts, seed_customer
):
    income = seed_accounts["4100"]
    item = authed_client.post(
        "/api/items",
        json={
            "name": "Duplicate mapped service",
            "item_type": "service",
            "rate": 20,
            "income_account_id": income.id,
        },
    )
    assert item.status_code == 201, item.text
    created = authed_client.post(
        "/api/invoices",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-09-08",
            "lines": [
                {"item_id": item.json()["id"], "quantity": 1, "rate": 20},
                {"description": "Zero", "quantity": 1, "rate": 0},
            ],
        },
    )
    assert created.status_code == 201, created.text
    duplicate = authed_client.post(f"/api/invoices/{created.json()['id']}/duplicate")
    assert duplicate.status_code == 201, duplicate.text
    stored = db_session.get(Invoice, duplicate.json()["id"])
    posted = (
        db_session.query(TransactionLine)
        .filter_by(transaction_id=stored.transaction_id)
        .all()
    )
    assert len(posted) == 2
    assert next(line for line in posted if line.credit > 0).account_id == income.id


def test_duplicate_preserves_job_and_class_attribution(
    authed_client, db_session, seed_accounts, seed_customer
):
    header = _job(authed_client, seed_customer.id, "Header")
    override = _job(authed_client, seed_customer.id, "Override")
    classes = []
    for name in ("Header class", "Line class"):
        response = authed_client.post("/api/classes", json={"name": name})
        assert response.status_code == 201, response.text
        classes.append(response.json()["id"])
    response = authed_client.post(
        "/api/invoices",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-04-01",
            "job_id": header["id"],
            "class_id": classes[0],
            "lines": [
                {"description": "Default", "quantity": 1, "rate": 10},
                {
                    "description": "Override",
                    "quantity": 1,
                    "rate": 20,
                    "job_id": override["id"],
                    "class_id": classes[1],
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    original = response.json()
    result = authed_client.post(f"/api/invoices/{original['id']}/duplicate")
    assert result.status_code == 201, result.text
    duplicate = db_session.get(Invoice, result.json()["id"])
    assert duplicate.job_id == header["id"]
    assert duplicate.class_id == classes[0]
    line = next(row for row in duplicate.lines if row.description == "Override")
    assert (line.job_id, line.class_id) == (override["id"], classes[1])
    transaction = db_session.get(Transaction, duplicate.transaction_id)
    assert transaction.job_id == header["id"]
    lines = (
        db_session.query(TransactionLine).filter_by(transaction_id=transaction.id).all()
    )
    default = next(row for row in lines if row.description == "Default")
    overridden = next(row for row in lines if row.description == "Override")
    assert (default.job_id, default.class_id) == (header["id"], classes[0])
    assert (overridden.job_id, overridden.class_id) == (override["id"], classes[1])
    assert sum(row.debit for row in lines) == sum(row.credit for row in lines) == 30


@pytest.mark.parametrize("action", ["send", "void", "duplicate", "write-off"])
def test_missing_invoice_lifecycle_rejected(authed_client, action):
    response = authed_client.post(
        f"/api/invoices/999999/{action}", json={"date": "2026-09-08"}
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "terms, days", [(None, 30), ("Due on receipt", 0), ("Net 15", 15), ("Unknown", 30)]
)
def test_duplicate_due_date_and_fresh_status(
    authed_client, db_session, seed_accounts, seed_customer, terms, days
):
    original = _create_invoice(authed_client, seed_customer.id)
    stored = db_session.get(Invoice, original["id"])
    stored.terms = terms
    db_session.commit()
    result = authed_client.post(f"/api/invoices/{original['id']}/duplicate")
    assert result.status_code == 201, result.text
    copy = result.json()
    assert copy["invoice_number"] != original["invoice_number"]
    assert copy["status"] == "draft"
    assert copy["due_date"] == (date.today() + timedelta(days=days)).isoformat()
    assert Decimal(copy["amount_paid"]) == 0
    assert Decimal(copy["balance_due"]) == Decimal(copy["total"]) == 100
    url = f"/api/invoices/{copy['id']}"
    assert authed_client.post(f"{url}/send").status_code == 200
    assert authed_client.post(f"{url}/send").status_code == 400
    assert authed_client.post(f"{url}/void").status_code == 200
    assert authed_client.post(f"{url}/void").status_code == 400
    assert (
        authed_client.post(f"{url}/write-off", json={"date": "2026-09-08"}).status_code
        == 400
    )
