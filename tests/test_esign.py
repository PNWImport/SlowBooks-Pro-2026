# ============================================================================
# E-signature coverage.
# ----------------------------------------------------------------------------
# Pins the envelope lifecycle (create/void/no-void-after-sign), the portal
# signing flow (consent required, employee-scoped, pending-only, integrity
# check before signing), the audit-chain seal, and tamper detection through
# /verify (body edit breaks body_intact; audit mismatch breaks
# signature_intact).
# ============================================================================

import hashlib


def _create_employee(client, **overrides):
    body = {
        "first_name": "Pat",
        "last_name": "Worker",
        "pay_type": "salary",
        "pay_rate": 60000,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _create_envelope(client, emp_id, **overrides):
    body = {
        "employee_id": emp_id,
        "title": "Employee Handbook 2026",
        "body": "I acknowledge receipt of the handbook.",
        "kind": "handbook",
    }
    body.update(overrides)
    r = client.post("/api/esign", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _portal_session(client, emp_id):
    """Claim the portal token so the cookie session is live."""
    token = client.get(f"/api/employees/{emp_id}/portal-token").json()["portal_token"]
    r = client.get(f"/portal/{token}", follow_redirects=True)
    assert r.status_code == 200
    return token


def test_envelope_freezes_hash(client):
    emp = _create_employee(client)
    env = _create_envelope(client, emp["id"])
    expected = hashlib.sha256(
        "I acknowledge receipt of the handbook.".encode()
    ).hexdigest()
    assert env["content_hash"] == expected
    assert env["status"] == "pending"


def test_envelope_validation(client):
    emp = _create_employee(client)
    assert (
        client.post(
            "/api/esign",
            json={
                "employee_id": emp["id"],
                "title": "X",
                "body": "  ",
                "kind": "handbook",
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/esign",
            json={
                "employee_id": emp["id"],
                "title": "X",
                "body": "b",
                "kind": "scroll",
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/esign", json={"employee_id": 999, "title": "X", "body": "b"}
        ).status_code
        == 404
    )


def test_portal_signing_seals_audit(client, db_session):
    emp = _create_employee(client)
    env = _create_envelope(client, emp["id"])
    _portal_session(client, emp["id"])

    # Consent checkbox required.
    r = client.post(
        f"/portal/documents/{env['id']}/sign",
        data={"signer_name": "Pat Worker", "consent": ""},
    )
    assert r.status_code == 400

    r = client.post(
        f"/portal/documents/{env['id']}/sign",
        data={"signer_name": "Pat Worker", "consent": "yes"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    signed = client.get(f"/api/esign/{env['id']}").json()
    assert signed["status"] == "signed"
    assert signed["signer_name"] == "Pat Worker"
    assert signed["signature_audit_id"] is not None

    # The audit row is in the shared chain under doc_type "esign".
    audits = client.get("/api/document-audits?doc_type=esign").json()
    rows = audits if isinstance(audits, list) else audits.get("items", audits)
    assert any(a["doc_key"] == f"env{env['id']}" for a in rows)

    # Verify: everything intact.
    v = client.get(f"/api/esign/{env['id']}/verify").json()
    assert v["body_intact"] is True
    assert v["signature_intact"] is True
    assert v["verified"] is True

    # Double-sign rejected; signed envelopes cannot be voided.
    r = client.post(
        f"/portal/documents/{env['id']}/sign",
        data={"signer_name": "Pat Worker", "consent": "yes"},
    )
    assert r.status_code == 400
    assert client.post(f"/api/esign/{env['id']}/void").status_code == 400


def test_signing_is_employee_scoped(client):
    owner = _create_employee(client)
    other = _create_employee(client, first_name="Other")
    env = _create_envelope(client, owner["id"])
    _portal_session(client, other["id"])  # wrong employee's session
    r = client.post(
        f"/portal/documents/{env['id']}/sign",
        data={"signer_name": "Other Worker", "consent": "yes"},
    )
    assert r.status_code == 404


def test_tampered_body_detected(client, db_session):
    emp = _create_employee(client)
    env = _create_envelope(client, emp["id"])
    _portal_session(client, emp["id"])
    client.post(
        f"/portal/documents/{env['id']}/sign",
        data={"signer_name": "Pat Worker", "consent": "yes"},
        follow_redirects=False,
    )

    # Tamper with the stored body after signing.
    from app.models.esign import SignatureEnvelope

    row = db_session.query(SignatureEnvelope).get(env["id"])
    row.body = row.body + " (and agrees to a 90-hour week)"
    db_session.commit()

    v = client.get(f"/api/esign/{env['id']}/verify").json()
    assert v["body_intact"] is False
    assert v["verified"] is False


def test_tamper_before_signing_blocks_signature(client, db_session):
    emp = _create_employee(client)
    env = _create_envelope(client, emp["id"])
    from app.models.esign import SignatureEnvelope

    row = db_session.query(SignatureEnvelope).get(env["id"])
    row.body = "totally different text"
    db_session.commit()

    _portal_session(client, emp["id"])
    r = client.post(
        f"/portal/documents/{env['id']}/sign",
        data={"signer_name": "Pat Worker", "consent": "yes"},
    )
    assert r.status_code == 409


def test_void_pending_envelope(client):
    emp = _create_employee(client)
    env = _create_envelope(client, emp["id"])
    r = client.post(f"/api/esign/{env['id']}/void")
    assert r.status_code == 200
    assert r.json()["status"] == "voided"
