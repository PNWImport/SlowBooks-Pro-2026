"""Public error text must not contain driver/provider exception payloads."""

from decimal import InvalidOperation

import pytest
from sqlalchemy.exc import IntegrityError, StatementError

from app.services.safe_errors import DataProblem, GENERIC, safe_message


@pytest.mark.parametrize("exc_type", [DataProblem, ValueError, RuntimeError])
def test_error_logging_cannot_forge_lines(caplog, exc_type):
    import logging

    with caplog.at_level(logging.INFO, logger="app.services.safe_errors"):
        try:
            raise exc_type("bad value\r\nFORGED admin login")
        except Exception as exc:
            safe_message(exc, "import\nFORGED context")
    records = [r for r in caplog.records if r.name == "app.services.safe_errors"]
    assert len(records) == 1
    assert "FORGED" in records[0].getMessage()
    assert "\n" not in records[0].getMessage()
    assert "\r" not in records[0].getMessage()
    assert records[0].exc_info is None


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("synthetic-private-value"),
        KeyError("synthetic-private-value"),
        RuntimeError("synthetic-private-value"),
        StatementError(
            "synthetic-private-value",
            "SELECT synthetic-private-value",
            {},
            Exception("synthetic-private-value"),
        ),
    ],
)
def test_exception_payload_is_not_public(exc):
    try:
        raise exc
    except Exception as caught:
        message = safe_message(caught, "regression")
    assert "synthetic-private" not in message
    assert "server log" in message


def test_integrity_error_shows_only_the_drivers_first_line():
    # Upstream's contract: the constraint's own first line is the useful
    # part; the statement and its parameters never reach the message.
    exc = IntegrityError(
        "INSERT synthetic-statement-text",
        {"password": "synthetic-private-param"},
        Exception("NOT NULL constraint failed: t.c\nsecond line synthetic-extra"),
    )
    try:
        raise exc
    except Exception as caught:
        message = safe_message(caught, "regression")
    assert message == "Database constraint: NOT NULL constraint failed: t.c"
    for private in ("synthetic-statement", "synthetic-private-param", "synthetic-extra"):
        assert private not in message


def test_only_explicit_user_text_passes_through():
    assert safe_message(DataProblem("Choose an account")) == "Choose an account"
    assert safe_message(ValueError("Choose an account")) == GENERIC
    assert safe_message(InvalidOperation()) == "a number could not be read"


def test_widget_failure_is_private_and_does_not_hide_healthy_card(monkeypatch):
    from app.services import dashboard_widgets as widgets

    def fail(db):
        raise ValueError("synthetic-private-widget-data")

    monkeypatch.setitem(widgets.WIDGETS, "failed", ("Failed", "small", "", fail))
    monkeypatch.setitem(
        widgets.WIDGETS, "healthy", ("Healthy", "small", "", lambda db: {"total": 12})
    )
    assert widgets.build(None, ["failed", "healthy", "unknown"]) == {
        "failed": {"error": GENERIC},
        "healthy": {"total": 12},
    }


def test_settings_email_hides_failure(client, db_session, monkeypatch):
    from app.services import email_service
    from app.services.settings_service import set_setting

    set_setting(db_session, "smtp_host", "smtp.example.invalid")
    db_session.commit()

    def fail(**kwargs):
        raise RuntimeError("synthetic-private-smtp-data")

    monkeypatch.setattr(email_service, "send_email", fail)
    response = client.post("/api/settings/test-email")
    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Email failed — see the email log for the reason"
    )
    assert "synthetic-private" not in response.text


def test_invoice_render_failure_is_private_in_response_and_email_log(
    client, db_session, seed_accounts, seed_customer, monkeypatch
):
    from app.models.email_log import EmailLog
    from app.routes.invoices import documents

    created = client.post(
        "/api/invoices",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-09-14",
            "lines": [{"description": "Work", "quantity": 1, "rate": 10}],
        },
    )
    assert created.status_code == 201, created.text
    invoice_id = created.json()["id"]

    def fail(*args, **kwargs):
        raise ValueError("synthetic-private-render-data")

    monkeypatch.setattr(documents, "generate_invoice_pdf", fail)
    response = client.post(
        f"/api/invoices/{invoice_id}/email",
        json={"recipient": "recipient@example.invalid"},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "Email failed: " + GENERIC
    assert "synthetic-private" not in response.text
    log = db_session.query(EmailLog).filter_by(entity_id=invoice_id).one()
    assert log.status == "failed"
    assert log.error_message == GENERIC
