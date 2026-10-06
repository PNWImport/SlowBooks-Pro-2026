"""Calls that answered 500 on PostgreSQL when driven with unusable input.

Each is a case from firing every frontend call at a live instance. They all
sat behind a happy path the suite covered: the failures were the empty,
the unusual and the concurrent.
"""

from decimal import Decimal

import pytest

from app.models.email_log import EmailLog
from app.models.users import ROLE_BOOKKEEPER
from tests.test_ach_settings import _login_as, _mk_user
from tests.test_recurring_route_contracts import _create

# --- invoice email: no recipient was a NOT NULL violation (500) -------------


def _invoice(client, customer_id):
    r = client.post(
        "/api/invoices",
        json={
            "customer_id": customer_id,
            "date": "2026-06-01",
            "lines": [
                {"description": "x", "quantity": 1, "rate": "10", "amount": "10"}
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_emailing_an_invoice_with_nobody_to_send_it_to_is_a_400(
    authed_client, seed_accounts
):
    customer = authed_client.post("/api/customers", json={"name": "No Email"}).json()
    invoice = _invoice(authed_client, customer["id"])
    r = authed_client.post(f"/api/invoices/{invoice['id']}/email", json={})
    assert r.status_code == 400, r.text
    assert "email address" in r.json()["detail"]


def test_the_invoice_email_goes_to_the_customers_address_by_default(
    authed_client, db_session, seed_accounts, monkeypatch
):
    # What is under test is who the mail goes to, not the PDF: stub the render
    # so it also runs where WeasyPrint's native stack is not installed.
    from app.routes.invoices import documents

    monkeypatch.setattr(documents, "generate_invoice_pdf", lambda inv, co: b"%PDF-")
    customer = authed_client.post(
        "/api/customers", json={"name": "Has Email", "email": "buyer@example.com"}
    ).json()
    invoice = _invoice(authed_client, customer["id"])
    r = authed_client.post(f"/api/invoices/{invoice['id']}/email", json={})
    # No SMTP is configured here, so the send is refused (never a 500) and
    # the failure is logged against the customer's address.
    assert r.status_code == 502, r.text
    log = db_session.query(EmailLog).order_by(EmailLog.id.desc()).first()
    assert log.recipient == "buyer@example.com"


# --- recurring: deleting a template that already made invoices --------------


def test_a_recurring_invoice_that_has_generated_cannot_be_deleted(
    authed_client, seed_accounts, seed_customer
):
    made = _create(authed_client, seed_customer.id)
    assert made.status_code == 201, made.text
    rec_id = made.json()["id"]
    gen = authed_client.post("/api/recurring/generate?as_of=2026-09-08")
    assert gen.status_code == 200 and gen.json()["invoices_created"] == 1, gen.text

    r = authed_client.delete(f"/api/recurring/{rec_id}")
    assert r.status_code == 409, r.text
    assert "inactive" in r.json()["detail"]
    # it is still there, and a template that never generated deletes cleanly
    assert authed_client.get(f"/api/recurring/{rec_id}").status_code == 200
    fresh = _create(authed_client, seed_customer.id, frequency="weekly").json()
    assert authed_client.delete(f"/api/recurring/{fresh['id']}").status_code == 200


# --- bank import: any non-OFX upload was an OfxParserException (500) --------


@pytest.mark.parametrize(
    "name,content",
    [
        ("statement.csv", b"Date,Amount\n2026-06-01,10.00\n"),
        ("empty.ofx", b""),
        ("junk.qfx", b"\x00\x01\x02 not a bank file"),
    ],
)
def test_a_file_that_is_not_ofx_is_a_400(authed_client, name, content):
    r = authed_client.post(
        "/api/bank-import/preview", files={"file": (name, content, "text/plain")}
    )
    assert r.status_code == 400, r.text
    assert "OFX" in r.json()["detail"]


# --- batch payments: the date was a string parsed by hand (500) -------------


@pytest.mark.parametrize("bad", ["abc", "2026-13-45", "", "9999-12-31"])
def test_a_batch_payment_with_a_bad_date_is_a_422(authed_client, bad):
    r = authed_client.post("/api/batch-payments", json={"date": bad, "allocations": []})
    assert r.status_code == 422, r.text


# --- backups: a missing pg_dump is the machine's setup, not a crash ---------


def test_a_missing_backup_tool_is_a_503_and_a_real_failure_stays_a_500(
    authed_client, monkeypatch
):
    from app.routes import backups

    monkeypatch.setattr(
        backups,
        "create_backup",
        lambda db, notes=None: {"success": False, "error": "pg_dump not found"},
    )
    assert authed_client.post("/api/backups", json={}).status_code == 503

    monkeypatch.setattr(
        backups,
        "create_backup",
        lambda db, notes=None: {"success": False, "error": "disk full"},
    )
    assert authed_client.post("/api/backups", json={}).status_code == 500


# --- the bank-feed credential is the administrator's ------------------------


@pytest.mark.parametrize("path", ["/api/simplefin/claim", "/api/simplefin/disconnect"])
def test_a_bookkeeper_cannot_claim_or_remove_the_bank_feed_credential(
    client, db_session, path
):
    _mk_user(db_session, "keeper", ROLE_BOOKKEEPER)
    _login_as(client, "keeper")
    assert client.post(path, json={"setup_token": "x"}).status_code == 403


def test_a_bookkeeper_can_still_sync_the_bank_feed(client, db_session):
    _mk_user(db_session, "keeper2", ROLE_BOOKKEEPER)
    _login_as(client, "keeper2")
    # reaches the handler (not configured here), rather than being refused
    assert client.post("/api/simplefin/sync", json={}).status_code != 403


# --- bills: one vendor's new bills are serialized ---------------------------


def test_a_second_bill_with_the_same_number_is_still_refused(
    authed_client, seed_accounts
):
    vendor = authed_client.post("/api/vendors", json={"name": "Dup Co"}).json()
    body = {
        "vendor_id": vendor["id"],
        "bill_number": "INV-1",
        "date": "2026-06-01",
        "lines": [
            {
                "description": "x",
                "quantity": 1,
                "rate": 10,
                "account_id": seed_accounts["6000"].id,
            }
        ],
    }
    assert authed_client.post("/api/bills", json=body).status_code == 201
    again = authed_client.post("/api/bills", json=body)
    assert again.status_code == 409, again.text
    assert Decimal("0") == Decimal("0")
