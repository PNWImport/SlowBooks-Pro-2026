"""Invoice reversal must net to zero in each accounting dimension."""

from collections import defaultdict
from decimal import Decimal

from app.models.cost_codes import CostCode
from app.models.invoices import Invoice
from app.models.transactions import Transaction, TransactionLine
from tests.test_jobs import _job


def test_void_reverses_each_original_dimension(
    authed_client, db_session, seed_accounts, seed_customer
):
    jobs = [_job(authed_client, seed_customer.id, name)["id"] for name in ("A", "B")]
    classes = [
        authed_client.post("/api/classes", json={"name": name}).json()["id"]
        for name in ("A", "B")
    ]
    response = authed_client.post(
        "/api/invoices",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-04-01",
            "job_id": jobs[0],
            "class_id": classes[0],
            "lines": [
                {
                    "description": "Override",
                    "quantity": 1,
                    "rate": 100,
                    "job_id": jobs[1],
                    "class_id": classes[1],
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    invoice = db_session.get(Invoice, response.json()["id"])
    cost = CostCode(code="VOID", name="Historical labor", cost_type="labor")
    db_session.add(cost)
    db_session.flush()
    original = (
        db_session.query(TransactionLine)
        .filter_by(transaction_id=invoice.transaction_id)
        .all()
    )
    for line in original:
        line.cost_code_id = cost.id
        line.cost_type = "labor"
        line.function = "program"
    db_session.commit()
    result = authed_client.post(f"/api/invoices/{invoice.id}/void")
    assert result.status_code == 200, result.text
    reversal = (
        db_session.query(Transaction)
        .filter_by(source_type="invoice_void", source_id=invoice.id)
        .one()
    )
    reversed_lines = (
        db_session.query(TransactionLine).filter_by(transaction_id=reversal.id).all()
    )
    balances = defaultdict(Decimal)
    for line in original + reversed_lines:
        key = (
            line.account_id,
            line.job_id,
            line.class_id,
            line.cost_code_id,
            line.cost_type,
            line.function,
        )
        balances[key] += line.debit - line.credit
    assert len(reversed_lines) == len(original)
    assert all(value == 0 for value in balances.values()), dict(balances)
