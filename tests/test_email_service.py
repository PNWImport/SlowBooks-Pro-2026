"""SMTP is stubbed; message construction, encryption, and logs use real code."""

from datetime import date
from email import message_from_string
from types import SimpleNamespace as Obj

import pytest

from app.models.email_log import EmailLog
from app.models.email_templates import EmailTemplate
from app.services import email_service as email
from app.services.settings_service import set_setting


@pytest.fixture
def smtp_remote(monkeypatch):
    calls = []
    failures = set()

    class SMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))
            if "connect" in failures:
                raise OSError("synthetic connect failure")

        def starttls(self):
            calls.append(("tls",))
            if "tls" in failures:
                raise OSError("synthetic TLS failure")

        def login(self, user, password):
            calls.append(("login", user, password))

        def sendmail(self, sender, recipients, text):
            calls.append(("send", sender, recipients, text))
            if "send" in failures:
                raise OSError("synthetic send failure")

        def quit(self):
            calls.append(("quit",))
            if "quit" in failures:
                raise OSError("synthetic quit failure")

    monkeypatch.setattr(email.smtplib, "SMTP", SMTP)
    return calls, failures


def configure(db, tls=True):
    for key, value in {
        "smtp_host": "smtp.example.invalid",
        "smtp_port": "587",
        "smtp_user": "synthetic-user",
        "smtp_password": "synthetic-password",
        "smtp_from_email": "sender@example.invalid",
        "smtp_from_name": "Synthetic Sender",
        "smtp_use_tls": str(tls).lower(),
    }.items():
        set_setting(db, key, value)
    db.commit()


@pytest.mark.parametrize("tls", [False, True])
def test_message_attachment_headers_and_log(db_session, smtp_remote, tls):
    configure(db_session, tls)
    assert email.send_email(
        db_session,
        " recipient@example.invalid\r\n",
        "Invoice\r\nSynthetic",
        "<p>Synthetic</p>",
        b"synthetic attachment",
        "invoice.pdf",
        "invoice",
        42,
    )
    calls, _ = smtp_remote
    assert (("tls",) in calls) is tls
    assert ("login", "synthetic-user", "synthetic-password") in calls
    send = next(call for call in calls if call[0] == "send")
    assert send[1:3] == ("sender@example.invalid", ["recipient@example.invalid"])
    message = message_from_string(send[3])
    assert message["Subject"] == "Invoice Synthetic"
    assert message.get_payload()[1].get_filename() == "invoice.pdf"
    assert message.get_payload()[1].get_payload(decode=True) == b"synthetic attachment"
    log = db_session.query(EmailLog).one()
    assert (log.status, log.entity_type, log.entity_id) == ("sent", "invoice", 42)
    assert log.error_message is None


def test_unconfigured_smtp_logs_failure_without_network(db_session, smtp_remote):
    assert not email.send_email(
        db_session, "recipient@example.invalid", "Synthetic", "Body"
    )
    assert smtp_remote[0] == []
    log = db_session.query(EmailLog).one()
    assert log.status == "failed" and log.error_message == "SMTP not configured"


@pytest.mark.parametrize("failures", [{"connect"}, {"tls"}, {"send"}, {"send", "quit"}])
def test_transport_failure_is_logged(db_session, smtp_remote, failures):
    configure(db_session)
    smtp_remote[1].update(failures)
    assert not email.send_email(
        db_session, "recipient@example.invalid", "Synthetic", "Body"
    )
    log = db_session.query(EmailLog).one()
    assert log.status == "failed"
    assert "synthetic" in log.error_message
    if "connect" not in failures:
        assert ("quit",) in smtp_remote[0]


def test_database_template_escapes_context(db_session):
    assert email.render_template_from_db(db_session, "missing", {}) == (None, None)
    db_session.add(
        EmailTemplate(
            name="synthetic",
            template_type="invoice",
            subject_template="Invoice {{ name }}",
            body_template="<p>{{ name }} {{ amount|currency }} {{ day|fdate }}</p>",
        )
    )
    db_session.commit()
    subject, body = email.render_template_from_db(
        db_session,
        "synthetic",
        {"name": "<script>test</script>", "amount": 12.34, "day": date(2026, 1, 1)},
    )
    assert "<script>" not in subject + body
    assert "&lt;script&gt;" in body
    assert "$12.34" in body


@pytest.mark.parametrize("customer", [None, Obj(name="<script>test</script>")])
def test_invoice_template_failure_uses_escaped_fallback(monkeypatch, customer):
    def fail(*args):
        raise RuntimeError("synthetic template failure")

    monkeypatch.setattr(email._jinja_env, "get_template", fail)
    invoice = Obj(
        customer=customer,
        invoice_number="<1>",
        total=12.34,
        due_date=date(2026, 1, 1),
        is_sales_receipt=False,
    )
    html = email.render_invoice_email(invoice, {"company_name": "<Company>"})
    assert "&lt;Company&gt;" in html and "&lt;1&gt;" in html
    assert "<script>" not in html
    assert "$12.34" in html


def test_invoice_file_template_renders_escaped_customer():
    invoice = Obj(
        customer=Obj(name="<Synthetic>"),
        invoice_number="EMAIL-1",
        date=date(2026, 1, 1),
        due_date=date(2026, 1, 31),
        terms="Net 30",
        balance_due=12.34,
        total=12.34,
        notes="<Memo>",
        is_sales_receipt=False,
    )
    html = email.render_invoice_email(
        invoice,
        {"company_name": "Synthetic Company"},
        pay_url="https://example.invalid/pay",
    )
    assert "&lt;Synthetic&gt;" in html and "&lt;Memo&gt;" in html
    assert "Amount Due: $12.34" in html
    assert "https://example.invalid/pay" in html
