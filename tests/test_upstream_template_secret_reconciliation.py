"""Local regression for upstream 2fd6758; no mail or provider calls."""

from datetime import date

import pytest

from app.models.email_templates import EmailTemplate
from app.services.donor_documents import ACK_TEMPLATE_NAME, render_acknowledgment
from app.services.settings_service import (
    ENCRYPTED_SETTINGS_KEYS,
    get_all_settings,
    set_setting,
)


@pytest.mark.parametrize("key", sorted(ENCRYPTED_SETTINGS_KEYS))
@pytest.mark.parametrize("whole_dict", [False, True])
def test_editable_acknowledgment_masks_credentials(
    db_session, seed_customer, key, whole_dict
):
    canary = "synthetic-upstream-regression-value"
    set_setting(db_session, key, canary)
    set_setting(db_session, "company_name", "Safe Company")
    expression = "{{ company }}" if whole_dict else "{{ company." + key + " }}"
    db_session.add(
        EmailTemplate(
            name=ACK_TEMPLATE_NAME,
            template_type="invoice",
            subject_template=expression,
            body_template="{{ company.company_name }} " + expression,
        )
    )
    db_session.commit()
    company = get_all_settings(db_session)
    gift = {
        "id": 1,
        "number": "G-1",
        "date": date(2026, 9, 14),
        "amount": 100,
        "description": "",
        "fair_value_amount": None,
        "fair_value_description": None,
        "in_kind_lines": [],
        "customer_id": seed_customer.id,
    }
    subject, body = render_acknowledgment(db_session, company, seed_customer, gift)
    assert canary not in subject
    assert canary not in body
    assert "********" in subject
    assert "********" in body
    assert "Safe Company" in body
    # Rendering must not replace credentials needed by SMTP/provider callers.
    assert company[key] == canary
    assert get_all_settings(db_session)[key] == canary


def test_settings_and_templates_share_redaction_registry():
    from app.routes import settings
    from app.services.settings_service import redact_secrets

    assert settings.SECRET_KEYS is ENCRYPTED_SETTINGS_KEYS
    values = {key: "synthetic-value" for key in ENCRYPTED_SETTINGS_KEYS}
    values.update(company_name="Safe Company", smtp_password="", qbo_refresh_token=None)
    redacted = redact_secrets(values)
    assert redacted == settings._redact_secrets(values)
    assert redacted["smtp_password"] == ""
    assert redacted["qbo_refresh_token"] is None
    assert redacted["company_name"] == "Safe Company"
    assert redacted["stripe_secret_key"] == "********"
    assert values["stripe_secret_key"] == "synthetic-value"
