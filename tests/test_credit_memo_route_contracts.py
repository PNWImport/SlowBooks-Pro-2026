"""Credit memo CRUD, posting, application and void contracts."""

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.credit_memos import CreditMemo
from app.models.invoices import Invoice
from app.models.transactions import Transaction, TransactionLine
from app.routes import credit_memos
from app.schemas.credit_memos import CreditMemoCreate
from tests.test_credit_memo_application_boundaries import _credit
from tests.test_invoice_posting import _create_invoice
from tests.test_jobs import _job
from tests.test_inventory_integration import _seed_stock, _seed_vendor, _tracked_item


def test_credit_memo_list_get_filters_and_pagination(
    authed_client, seed_accounts, seed_customer
):
    first = _credit(authed_client, seed_customer.id, 10)
    second = _credit(authed_client, seed_customer.id, 20)
    fetched = authed_client.get(f"/api/credit-memos/{first['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["customer_name"] == seed_customer.name
    listed = authed_client.get(
        f"/api/credit-memos?customer_id={seed_customer.id}&status=issued"
    ).json()
    assert {row["id"] for row in listed} == {first["id"], second["id"]}
    assert len(authed_client.get("/api/credit-memos?skip=1&limit=1").json()) == 1
    assert authed_client.get("/api/credit-memos/999999").status_code == 404
    missing = authed_client.post(
        "/api/credit-memos",
        json={
            "customer_id": 999999,
            "date": "2026-09-08",
            "lines": [{"quantity": 1, "rate": 1}],
        },
    )
    assert missing.status_code == 404


def test_credit_memo_item_tax_zero_and_job_posting(
    authed_client, db_session, seed_accounts, seed_customer
):
    job = _job(authed_client, seed_customer.id, "Credit project")
    income = seed_accounts["4100"]
    item = authed_client.post(
        "/api/items",
        json={
            "name": "Credited service",
            "item_type": "service",
            "rate": 100,
            "income_account_id": income.id,
        },
    )
    assert item.status_code == 201, item.text
    response = authed_client.post(
        "/api/credit-memos",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-09-08",
            "job_id": job["id"],
            "tax_rate": 0.10,
            "lines": [
                {"item_id": item.json()["id"], "quantity": 1, "rate": 100},
                {"description": "Zero", "quantity": 1, "rate": 0},
            ],
        },
    )
    assert response.status_code == 201, response.text
    memo = db_session.get(CreditMemo, response.json()["id"])
    assert memo.total == Decimal("110")
    transaction = db_session.get(Transaction, memo.transaction_id)
    assert transaction.job_id == job["id"]
    lines = (
        db_session.query(TransactionLine).filter_by(transaction_id=transaction.id).all()
    )
    assert len(lines) == 3
    assert all(line.job_id == job["id"] for line in lines)
    assert (
        next(line for line in lines if line.description == "").account_id == income.id
    )
    assert (
        sum(line.debit for line in lines) == sum(line.credit for line in lines) == 110
    )


def test_credit_apply_edges_and_void_restores_invoice(
    authed_client, db_session, seed_accounts, seed_customer
):
    credit = _credit(authed_client, seed_customer.id, 75)
    invoice = _create_invoice(authed_client, seed_customer.id)
    base = f"/api/credit-memos/{credit['id']}"
    assert (
        authed_client.post(
            "/api/credit-memos/999999/apply",
            json={"invoice_id": invoice["id"], "amount": 1},
        ).status_code
        == 404
    )
    assert (
        authed_client.post(
            f"{base}/apply", json={"invoice_id": 999999, "amount": 1}
        ).status_code
        == 404
    )
    assert (
        authed_client.post(
            f"{base}/apply", json={"invoice_id": invoice["id"], "amount": 76}
        ).status_code
        == 400
    )
    assert (
        authed_client.post(
            f"{base}/apply", json={"invoice_id": invoice["id"], "amount": 50}
        ).status_code
        == 200
    )
    assert (
        authed_client.post(
            f"{base}/apply", json={"invoice_id": invoice["id"], "amount": 25}
        ).status_code
        == 200
    )
    db_session.expire_all()
    assert db_session.get(CreditMemo, credit["id"]).status.value == "applied"
    assert db_session.get(Invoice, invoice["id"]).balance_due == 25
    voided = authed_client.post(f"{base}/void")
    assert voided.status_code == 200, voided.text
    db_session.expire_all()
    restored = db_session.get(Invoice, invoice["id"])
    assert restored.amount_paid == 0
    assert restored.balance_due == 100
    assert restored.status.value == "sent"
    assert (
        authed_client.post(
            f"{base}/apply", json={"invoice_id": invoice["id"], "amount": 1}
        ).status_code
        == 400
    )
    assert authed_client.post(f"{base}/void").status_code == 400
    assert authed_client.post("/api/credit-memos/999999/void").status_code == 404


def test_credit_cannot_exceed_smaller_invoice_balance(
    authed_client, seed_accounts, seed_customer
):
    credit = _credit(authed_client, seed_customer.id, 150)
    invoice = _create_invoice(authed_client, seed_customer.id)
    response = authed_client.post(
        f"/api/credit-memos/{credit['id']}/apply",
        json={"invoice_id": invoice["id"], "amount": 101},
    )
    assert response.status_code == 400
    assert "invoice balance" in response.json()["detail"]


def test_credit_without_chart_is_refused_before_posting(authed_client, seed_customer):
    response = authed_client.post(
        "/api/credit-memos",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-09-08",
            "lines": [{"description": "Credit", "quantity": 1, "rate": 10}],
        },
    )
    assert response.status_code == 409
    assert "1100 Accounts Receivable" in response.json()["detail"]


def test_void_credit_memo_reverses_inventory_return(
    authed_client, db_session, seed_accounts, seed_customer
):
    vendor = _seed_vendor(db_session)
    item = _tracked_item(db_session, seed_accounts, name="Void return")
    _seed_stock(authed_client, vendor.id, item.id, 10, 5)
    credit = authed_client.post(
        "/api/credit-memos",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-09-08",
            "lines": [
                {"item_id": item.id, "description": "Return", "quantity": 2, "rate": 10}
            ],
        },
    )
    assert credit.status_code == 201, credit.text
    db_session.expire_all()
    assert item.quantity_on_hand == 12
    voided = authed_client.post(f"/api/credit-memos/{credit.json()['id']}/void")
    assert voided.status_code == 200, voided.text
    db_session.expire_all()
    assert item.quantity_on_hand == 10


@pytest.mark.parametrize("mode", ["retry", "exhaust", "unrelated"])
def test_credit_memo_number_collision_handling(
    db_session, seed_accounts, seed_customer, monkeypatch, mode
):
    data = CreditMemoCreate(
        customer_id=seed_customer.id,
        date="2026-09-08",
        lines=[{"description": "Synthetic", "quantity": 1, "rate": 1}],
    )
    real_flush = db_session.flush
    attempts = 0

    def flush(*args, **kwargs):
        nonlocal attempts
        if not any(isinstance(row, CreditMemo) for row in db_session.new):
            return real_flush(*args, **kwargs)
        attempts += 1
        should_raise = mode != "retry" or attempts == 1
        if should_raise:
            message = (
                "other constraint" if mode == "unrelated" else "memo_number unique"
            )
            raise IntegrityError("synthetic", {}, Exception(message))
        return real_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", flush)
    if mode == "retry":
        result = credit_memos.create_credit_memo(data, db_session)
        assert result.customer_name == seed_customer.name
        assert attempts >= 2
    elif mode == "unrelated":
        with pytest.raises(IntegrityError):
            credit_memos.create_credit_memo(data, db_session)
    else:
        with pytest.raises(HTTPException) as caught:
            credit_memos.create_credit_memo(data, db_session)
        assert caught.value.status_code == 503
        assert attempts == 10
