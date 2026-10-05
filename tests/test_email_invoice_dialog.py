"""The Email Invoice dialog's own payload was rejected (issue #140, mdornich).

`_EmailInvoiceRequest` is a StrictModel accepting `recipient` and `subject`.
The dialog in `app/static/js/invoices.js` has always also posted `message`,
so **every send from the interface failed validation with a 422** before
reaching any of the sending code. The Message box did not merely get
ignored; it broke the button it sat on.

No test caught it because every test called the endpoint with a payload the
endpoint accepted, rather than the payload the interface sends. That is the
same shape as 2.10.3's shadowed download route: a test of the handler is not
a test of what the page does.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def invoice(client, seed_accounts):
    cust = client.post(
        "/api/customers", json={"name": "Probe Co", "email": "a@b.com"}
    ).json()
    r = client.post(
        "/api/invoices",
        json={
            "customer_id": cust["id"],
            "date": "2026-06-01",
            "due_date": "2026-06-30",
            "lines": [
                {"description": "work", "quantity": 1, "rate": 100, "line_order": 0}
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_the_payload_the_dialog_actually_sends_is_accepted(
    client, seed_accounts, invoice, monkeypatch
):
    """Prove the actual dialog payload reaches sending, independent of the
    host's native PDF stack and SMTP configuration (3690ec1)."""
    from app.routes.invoices import documents
    from app.services import email_service

    sent = []
    monkeypatch.setattr(documents, "generate_invoice_pdf", lambda *a: b"PDF")
    monkeypatch.setattr(
        email_service, "send_email", lambda **kw: sent.append(kw) or True
    )
    r = client.post(
        f"/api/invoices/{invoice['id']}/email",
        json={
            "recipient": "a@b.com",
            "subject": f"Invoice #{invoice['invoice_number']} from us",
            "message": f"Please find attached Invoice #{invoice['invoice_number']}.",
        },
    )
    assert r.status_code == 200, r.text
    assert len(sent) == 1
    assert sent[0]["to_email"] == "a@b.com"
    assert (
        f"Please find attached Invoice #{invoice['invoice_number']}."
        in sent[0]["html_body"]
    )


def test_an_unknown_field_is_still_refused_over_http(client, invoice):
    """cc5dc87: accepting message must not weaken the strict request model."""
    r = client.post(
        f"/api/invoices/{invoice['id']}/email",
        json={"recipient": "a@b.com", "message": "m", "nonsense": "x"},
    )
    assert r.status_code == 422
    assert any(e["type"] == "extra_forbidden" for e in r.json()["detail"])


def test_an_unknown_field_is_still_refused():
    """The control, and it is @macbase1's — their gate harness had it and my
    test did not.

    "The dialog's payload is accepted" is equally true of a fix that named
    `message` and of one that simply deleted the model's strictness. Only
    this tells them apart, and the second would be a far wider change than
    #140 asked for: `_EmailInvoiceRequest` is a StrictModel on purpose, so
    that a typo in the page is a loud 422 rather than a field silently
    dropped on the floor.

    It lives here as well as in the harness because CI runs this suite on
    every push and does not run the harness.
    """
    from app.routes.invoices.documents import _EmailInvoiceRequest
    import pydantic

    with pytest.raises(pydantic.ValidationError) as e:
        _EmailInvoiceRequest(
            recipient="a@b.com", subject="s", message="m", nonsense="x"
        )
    assert "extra_forbidden" in str(e.value)

    # And the four it does take still validate together.
    ok = _EmailInvoiceRequest(recipient="a@b.com", subject="s", message="m")
    assert ok.message == "m"


def test_the_dialog_and_the_route_agree_on_their_fields():
    """The tripwire. These two drifted apart and nothing noticed, because
    they are in different languages in different files."""
    js = (ROOT / "app/static/js/invoices.js").read_text(encoding="utf-8")
    py = (ROOT / "app/routes/invoices/documents.py").read_text(encoding="utf-8")

    body = re.search(r"API\.post\(`/invoices/\$\{id\}/email`,\s*\{(.+?)\}\)", js, re.S)
    assert body, "could not find the dialog's email POST"
    sent = set(re.findall(r"(\w+):", body.group(1)))

    model = re.search(r"class _EmailInvoiceRequest\(StrictModel\):(.+?)\n\n", py, re.S)
    assert model, "could not find _EmailInvoiceRequest"
    accepted = set(re.findall(r"^\s{4}(\w+):", model.group(1), re.M))

    assert sent <= accepted, (
        f"the dialog posts {sorted(sent - accepted)} which the route rejects; "
        f"_EmailInvoiceRequest is a StrictModel so this is a 422, not an ignore"
    )
    # The other direction, which @mdornich found by testing his own branch
    # against this test: it removed the Message box entirely and still passed
    # everything here. "The page stopped sending something the route
    # supports" was outside the window, and it is the likelier mistake now
    # that the field works. The box existing is part of the contract.
    assert "message" in sent, "the Email Invoice dialog no longer sends a message"
    assert "message" in accepted, "the route no longer accepts a message"


def test_the_dialog_calls_preview_and_renders_it_into_the_preview_pane():
    js = (ROOT / "app/static/js/invoices.js").read_text(encoding="utf-8")
    assert "API.post(`/invoices/${id}/email-preview`" in js
    # Production renders the preview into a plain pane (a div), not a sandboxed
    # iframe; the failure branch uses textContent so an error is never markup.
    assert 'id="email-preview"' in js and "sandbox" not in js[js.index('id="email-preview"') : js.index('id="email-preview"') + 200]
    assert "target.innerHTML = out.html_body" in js
    assert "target.textContent = `Preview unavailable" in js


def test_the_operators_message_reaches_the_email_body(
    client, db_session, seed_accounts, invoice
):
    """The box says Message. It should be the message."""
    from app.models.invoices import Invoice
    from app.services.email_service import render_invoice_email
    from app.services.settings_service import get_all_settings as get_settings

    inv = db_session.query(Invoice).filter(Invoice.id == invoice["id"]).first()
    body = render_invoice_email(
        inv, get_settings(db_session), note="Ten days, as agreed."
    )
    assert "Ten days, as agreed." in body


@pytest.mark.parametrize("fallback", [False, True])
def test_an_operator_message_is_escaped(
    client, db_session, seed_accounts, invoice, monkeypatch, fallback
):
    """It is operator-supplied text landing in an HTML email."""
    if fallback:
        from app.services import email_service

        def unavailable(*args):
            raise RuntimeError("synthetic missing template")

        monkeypatch.setattr(email_service._jinja_env, "get_template", unavailable)
    from app.models.invoices import Invoice
    from app.services.email_service import render_invoice_email
    from app.services.settings_service import get_all_settings as get_settings

    inv = db_session.query(Invoice).filter(Invoice.id == invoice["id"]).first()
    body = render_invoice_email(
        inv, get_settings(db_session), note="<script>x</script>"
    )
    assert "<script>x</script>" not in body
    assert "&lt;script&gt;" in body


# ── The saved template, which was never loaded by anything (#140 part 1) ──


def _save_invoice_template(client, subject, body):
    # Defaults are created on demand, not at install — a fresh company has no
    # invoice_email row at all, which is why the renderer has to fall through
    # to the built-in body rather than assume one exists.
    client.post("/api/email-templates/seed-defaults")
    tpls = client.get("/api/email-templates").json()
    tpl = [t for t in tpls if t["name"] == "invoice_email"]
    assert tpl, "the invoice_email template should be seeded"
    r = client.put(
        f"/api/email-templates/{tpl[0]['id']}",
        json={"subject_template": subject, "body_template": body},
    )
    assert r.status_code == 200, r.text


def test_the_saved_template_is_what_gets_sent(
    client, db_session, seed_accounts, invoice
):
    """Editing `invoice_email` under Settings saved correctly and changed
    nothing. `render_template_from_db` existed with exactly one caller — the
    donor acknowledgment — and the invoice path went straight to the file
    template."""
    from app.models.invoices import Invoice
    from app.services.email_service import render_invoice_email_parts
    from app.services.settings_service import get_all_settings as get_settings

    _save_invoice_template(
        client,
        "OBVIOUSLY CUSTOM {{ invoice.invoice_number }}",
        "<p>A body nobody would write by accident.</p>",
    )
    inv = db_session.query(Invoice).filter(Invoice.id == invoice["id"]).first()
    subject, body = render_invoice_email_parts(
        inv, get_settings(db_session), db=db_session
    )
    assert subject.startswith("OBVIOUSLY CUSTOM")
    assert "A body nobody would write by accident." in body
    assert "Please find attached" not in body


def test_without_a_database_the_built_in_body_is_used(
    client, db_session, seed_accounts, invoice
):
    """The renderer must still work for callers that have no session."""
    from app.models.invoices import Invoice
    from app.services.email_service import render_invoice_email_parts
    from app.services.settings_service import get_all_settings as get_settings

    inv = db_session.query(Invoice).filter(Invoice.id == invoice["id"]).first()
    _, body = render_invoice_email_parts(inv, get_settings(db_session))
    assert "Please find attached" in body


def test_a_broken_saved_template_does_not_stop_the_mail(
    client, db_session, seed_accounts, invoice
):
    """A template is operator-authored text. A bad expression in it must not
    be the reason an invoice never goes out."""
    from app.models.invoices import Invoice
    from app.services.email_service import render_invoice_email_parts
    from app.services.settings_service import get_all_settings as get_settings

    _save_invoice_template(client, "S", "{{ nope.does.not.exist | frobnicate }}")
    inv = db_session.query(Invoice).filter(Invoice.id == invoice["id"]).first()
    _, body = render_invoice_email_parts(inv, get_settings(db_session), db=db_session)
    assert "Please find attached" in body, "should fall through to the built-in body"


def test_the_note_survives_a_saved_template_that_never_mentions_it(
    client, db_session, seed_accounts, invoice
):
    """The design decision, and @mdornich's call. If the note were a
    `{{ note }}` context variable, a saved template that does not reference
    it would drop the operator's message silently — the same failure class
    #140 is about, moved rather than fixed. It is prepended, always."""
    from app.models.invoices import Invoice
    from app.services.email_service import render_invoice_email_parts
    from app.services.settings_service import get_all_settings as get_settings

    _save_invoice_template(client, "S", "<p>No mention of any note here.</p>")
    inv = db_session.query(Invoice).filter(Invoice.id == invoice["id"]).first()
    _, body = render_invoice_email_parts(
        inv, get_settings(db_session), note="Ten days, as agreed.", db=db_session
    )
    assert "Ten days, as agreed." in body
    assert body.index("Ten days") < body.index("No mention"), "the note goes above"


def test_a_sales_receipt_still_uses_the_saved_invoice_template(
    client, db_session, seed_accounts, invoice
):
    """#140 part three. `invoice_email_label()` answers 'Sales Receipt' for
    that kind, so selecting a template by the document's face would skip the
    saved template for every sales receipt — ordinary businesses, not just
    nonprofit installs. The lookup is the fixed name `invoice_email`."""
    from app.models.invoices import Invoice
    from app.services.email_service import (
        render_invoice_email_parts,
        invoice_email_label,
    )
    from app.services.settings_service import get_all_settings as get_settings

    _save_invoice_template(client, "S", "<p>CUSTOM BODY</p>")
    inv = db_session.query(Invoice).filter(Invoice.id == invoice["id"]).first()
    company = get_settings(db_session)

    # Whatever the document is called, the same template is used.
    label = invoice_email_label(inv, company)
    _, body = render_invoice_email_parts(inv, company, db=db_session)
    assert "CUSTOM BODY" in body, f"label was {label!r} and the template was skipped"


def test_the_preview_returns_what_the_send_would_produce(
    client, db_session, seed_accounts, invoice
):
    """A read-only endpoint that renders through the same code as the send.
    It exists because an operator editing the template had no way to see the
    result short of mailing a real customer."""
    from app.models.email_log import EmailLog

    _save_invoice_template(client, "SUBJ {{ invoice.invoice_number }}", "<p>BODY</p>")
    before = db_session.query(EmailLog).count()

    r = client.post(
        f"/api/invoices/{invoice['id']}/email-preview",
        json={"recipient": "a@b.com", "message": "Hello there."},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["subject"] == f"SUBJ {invoice['invoice_number']}"
    assert "BODY" in out["html_body"]
    assert "Hello there." in out["html_body"]
    # Read-only: nothing sent, nothing logged.
    assert db_session.query(EmailLog).count() == before
