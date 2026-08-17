# ============================================================================
# Signed + off-boxable audit checkpoints.
# ----------------------------------------------------------------------------
# The hash chain in test_document_audit_integrity.py catches alteration,
# deletion and reordering; checkpoints catch tail truncation. The hole both
# leave open is an attacker with full database write access who deletes the
# audit rows AND the checkpoints.
#
# Two things close it, and both are tested here:
#   * a signature under a key held outside the database, so a checkpoint
#     cannot be FORGED
#   * an exported artifact that verifies against the live chain with no
#     checkpoint row present, so DELETING them all still gets noticed
#
# The signing key is set per-test via monkeypatch on os.environ, because the
# whole point is that the default is nothing at all — a signature under a
# well-known development key would look like proof while providing none.
# ============================================================================

import json

import pytest

from app.services import audit_signing
from app.services.document_audit import (
    create_checkpoint,
    export_checkpoint,
    record_doc_audit,
    resign_checkpoints,
    verify_against_checkpoint,
    verify_artifact,
    verify_checkpoint_signature,
)

KEY = "operator-held-checkpoint-key-not-the-payroll-one"
OTHER_KEY = "an-attackers-guess-at-the-signing-key"


@pytest.fixture
def signing_key(monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", KEY)
    monkeypatch.setenv("AUDIT_CHECKPOINT_KEY_ID", "test-key-1")
    monkeypatch.delenv("AUDIT_CHECKPOINT_SIGNING_SECRET_PREV", raising=False)
    return KEY


@pytest.fixture
def no_signing_key(monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", "")
    monkeypatch.delenv("AUDIT_CHECKPOINT_SIGNING_SECRET_PREV", raising=False)


def _chain(db, rows=3):
    """Put some rows in the chain so there is something to checkpoint."""
    for i in range(rows):
        record_doc_audit(db, "test", f"k{i}", f"{i:064x}")


# --- configuration is fail-visible, not fail-open ---------------------------


def test_no_default_signing_key(no_signing_key):
    """A well-known default would be worse than nothing: it looks like proof."""
    assert audit_signing.signing_configured() is False
    assert audit_signing.current_key() is None


def test_signing_key_is_not_the_payroll_encryption_key(signing_key):
    """Separate keys, separate blast radius. A leaked PII key must not also
    let an attacker mint checkpoints."""
    from app.config import PAYROLL_ENCRYPTION_SECRET

    key_id, secret = audit_signing.current_key()
    assert secret == KEY
    assert secret != PAYROLL_ENCRYPTION_SECRET
    assert key_id == "test-key-1"


def test_unsigned_checkpoint_is_reported_not_silently_accepted(
    db_session, no_signing_key
):
    _chain(db_session)
    cp = create_checkpoint(db_session, note="unsigned run")
    assert cp.signature is None

    result = verify_against_checkpoint(db_session, cp)
    # Containment is fine — nothing was truncated...
    assert result["contains_checkpointed_state"] is True
    assert result["problems"] == []
    # ...but "we cannot tell" must never read as "verified".
    assert result["ok"] is False
    assert result["signature"]["status"] == "unsigned"
    assert result["signature"]["ok"] is False


# --- signing ----------------------------------------------------------------


def test_checkpoint_is_signed_when_a_key_is_configured(db_session, signing_key):
    _chain(db_session)
    cp = create_checkpoint(db_session, note="Q3 close")

    assert cp.signature and len(cp.signature) == 64
    assert int(cp.signature, 16) >= 0  # valid hex
    assert cp.signature_key_id == "test-key-1"
    assert cp.signature_algorithm == "HMAC-SHA256"
    assert verify_checkpoint_signature(cp)["status"] == "valid"


def test_signed_checkpoint_verifies_end_to_end(db_session, signing_key):
    _chain(db_session)
    cp = create_checkpoint(db_session)
    result = verify_against_checkpoint(db_session, cp)
    assert result["ok"] is True
    assert result["signature"]["status"] == "valid"
    assert result["signature"]["key_id"] == "test-key-1"


@pytest.mark.parametrize(
    "field,value",
    [
        ("row_count", 1),
        ("tip_audit_id", 9999),
        ("tip_chain_hash", "d" * 64),
        ("note", "a different label"),
    ],
)
def test_editing_a_signed_field_invalidates_the_signature(
    db_session, signing_key, field, value
):
    """Every part of the pinned tuple is inside the MAC — including the note,
    because the operator's label is part of what the checkpoint asserts."""
    _chain(db_session)
    cp = create_checkpoint(db_session, note="original label")
    assert verify_checkpoint_signature(cp)["status"] == "valid"

    setattr(cp, field, value)
    db_session.commit()

    state = verify_checkpoint_signature(cp)
    assert state["status"] == "invalid"
    assert state["ok"] is False
    assert "altered" in state["detail"] or "forged" in state["detail"]


def test_back_dating_a_checkpoint_invalidates_the_signature(db_session, signing_key):
    """created_at is signed, so a checkpoint cannot be re-dated to look like
    it covered rows it never saw."""
    from datetime import datetime, timezone

    _chain(db_session)
    cp = create_checkpoint(db_session)
    cp.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.commit()

    assert verify_checkpoint_signature(cp)["status"] == "invalid"


def test_an_attacker_without_the_key_cannot_forge_a_checkpoint(
    db_session, signing_key, monkeypatch
):
    """The actual threat model: full DB write access, no application host.
    They can insert whatever row they like — it just will not verify."""
    from app.models.document_audit import AuditCheckpoint

    _chain(db_session)
    real = create_checkpoint(db_session, note="real")

    forged_payload = audit_signing.build_payload(
        tip_audit_id=real.tip_audit_id,
        tip_chain_hash=real.tip_chain_hash,
        row_count=1,  # pretending the chain was always this short
        created_at=real.created_at,
        note="real",
    )
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", OTHER_KEY)
    forged_signature = audit_signing.sign(forged_payload)["signature"]
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", KEY)

    forged = AuditCheckpoint(
        tip_audit_id=real.tip_audit_id,
        tip_chain_hash=real.tip_chain_hash,
        row_count=1,
        note="real",
        created_at=real.created_at,
        signature=forged_signature,
        signature_key_id="test-key-1",
        signature_algorithm="HMAC-SHA256",
    )
    db_session.add(forged)
    db_session.commit()

    assert verify_checkpoint_signature(forged)["status"] == "invalid"
    assert verify_against_checkpoint(db_session, forged)["ok"] is False


def test_signature_is_unverifiable_when_the_key_is_gone(
    db_session, signing_key, monkeypatch
):
    """A host with no key must say 'cannot tell', not 'invalid' — the
    difference matters when triaging."""
    _chain(db_session)
    cp = create_checkpoint(db_session)
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", "")
    state = verify_checkpoint_signature(cp)
    assert state["status"] == "unverifiable"
    assert state["ok"] is False


# --- key rotation -----------------------------------------------------------


def test_rotation_reports_valid_previous_key_then_resigns(
    db_session, signing_key, monkeypatch
):
    _chain(db_session)
    cp = create_checkpoint(db_session)
    original_signature = cp.signature

    # Rotate: current becomes PREV, a new key becomes current.
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET_PREV", KEY)
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", "the-rotated-in-key")
    monkeypatch.setenv("AUDIT_CHECKPOINT_KEY_ID", "test-key-2")

    state = verify_checkpoint_signature(cp)
    assert state["status"] == "valid_previous_key"
    assert state["ok"] is True  # genuine, just due for re-signing

    summary = resign_checkpoints(db_session)
    assert summary["resigned"] == 1
    assert summary["left_unsigned"] == 0
    db_session.refresh(cp)
    assert cp.signature != original_signature
    assert cp.signature_key_id == "test-key-2"
    assert verify_checkpoint_signature(cp)["status"] == "valid"

    # And once PREV is dropped it still verifies.
    monkeypatch.delenv("AUDIT_CHECKPOINT_SIGNING_SECRET_PREV")
    assert verify_checkpoint_signature(cp)["status"] == "valid"


def test_resign_refuses_to_back_sign_an_unsigned_checkpoint(
    db_session, monkeypatch, no_signing_key
):
    """Signing an already-unsigned checkpoint would assert something nobody
    can know — and would launder a checkpoint an attacker had inserted."""
    _chain(db_session)
    cp = create_checkpoint(db_session)
    assert cp.signature is None

    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", KEY)
    summary = resign_checkpoints(db_session)
    assert summary["left_unsigned"] == 1
    assert summary["resigned"] == 0
    db_session.refresh(cp)
    assert cp.signature is None


def test_resign_without_a_key_reports_an_error(db_session, no_signing_key):
    _chain(db_session)
    create_checkpoint(db_session)
    summary = resign_checkpoints(db_session)
    assert "error" in summary
    assert summary["resigned"] == 0


# --- off-box artifacts ------------------------------------------------------


def test_artifact_is_self_contained_and_json_serializable(db_session, signing_key):
    _chain(db_session)
    cp = create_checkpoint(db_session, note="worm copy")
    artifact = export_checkpoint(cp)

    # Must survive a round trip through a file — that is the whole point.
    reloaded = json.loads(json.dumps(artifact))
    assert reloaded["artifact"] == "slowbooks-audit-checkpoint"
    assert reloaded["signature"] == cp.signature
    assert reloaded["payload"]["tip_chain_hash"] == cp.tip_chain_hash
    assert reloaded["payload"]["row_count"] == cp.row_count
    assert reloaded["payload"]["note"] == "worm copy"


def test_artifact_signature_is_reproducible_offline(db_session, signing_key):
    """An auditor with the key and the artifact must be able to verify with
    stock library calls — no SlowBooks install required."""
    import hashlib
    import hmac

    _chain(db_session)
    artifact = export_checkpoint(create_checkpoint(db_session, note="offline"))

    canonical = json.dumps(
        artifact["payload"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    expected = hmac.new(KEY.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    assert expected == artifact["signature"]


def test_artifact_verifies_against_a_clean_chain(db_session, signing_key):
    _chain(db_session)
    artifact = export_checkpoint(create_checkpoint(db_session))
    result = verify_artifact(db_session, artifact)
    assert result["ok"] is True
    assert result["checkpoint_row_present"] is True
    assert result["problems"] == []


def test_artifact_catches_truncation_after_every_checkpoint_is_deleted(
    db_session, signing_key
):
    """THE case the in-database checkpoint could never cover: an attacker with
    full write access deletes the audit tail AND every checkpoint row."""
    from app.models.document_audit import AuditCheckpoint, DocumentAudit

    _chain(db_session, rows=4)
    artifact = export_checkpoint(create_checkpoint(db_session, note="pre-attack"))

    tip = db_session.query(DocumentAudit).order_by(DocumentAudit.id.desc()).first()
    db_session.delete(tip)
    db_session.query(AuditCheckpoint).delete()
    db_session.commit()

    # Nothing left in the database notices...
    assert db_session.query(AuditCheckpoint).count() == 0
    from app.services.document_audit import verify_chain

    assert verify_chain(db_session)["ok"] is True  # a short chain is still valid

    # ...but the off-box artifact does.
    result = verify_artifact(db_session, artifact)
    assert result["ok"] is False
    assert result["checkpoint_row_present"] is False
    assert result["signature"]["ok"] is True  # the artifact itself is genuine
    assert any("truncated" in p for p in result["problems"])
    assert any("row count fell" in p for p in result["problems"])
    assert any("no longer holds a checkpoint" in p for p in result["problems"])


def test_tampering_with_an_artifact_payload_is_caught(db_session, signing_key):
    _chain(db_session)
    artifact = export_checkpoint(create_checkpoint(db_session))
    artifact["payload"]["row_count"] = 1  # make the truncation look expected

    result = verify_artifact(db_session, artifact)
    assert result["signature"]["status"] == "invalid"
    assert result["ok"] is False


def test_artifact_with_an_unknown_extra_payload_key_still_verifies(
    db_session, signing_key
):
    """Canonicalization signs whatever keys the payload carries, so an
    artifact from a future version does not fail here for the wrong reason."""
    payload = audit_signing.build_payload(
        tip_audit_id=1,
        tip_chain_hash="a" * 64,
        row_count=1,
        created_at="2026-08-19T00:00:00+00:00",
        note="",
    )
    payload["future_field"] = "something this build knows nothing about"
    signature = audit_signing.sign(payload)["signature"]
    assert audit_signing.verify(payload, signature)["status"] == "valid"


def test_malformed_artifact_raises_rather_than_passing(db_session, signing_key):
    with pytest.raises(ValueError):
        verify_artifact(db_session, {"payload": {"tip_audit_id": 1}})
    with pytest.raises(ValueError):
        verify_artifact(db_session, {"payload": "not an object"})


def test_artifact_rejects_a_payload_version_it_does_not_understand(signing_key):
    payload = audit_signing.build_payload(
        tip_audit_id=1,
        tip_chain_hash="a" * 64,
        row_count=1,
        created_at="2026-08-19T00:00:00+00:00",
    )
    payload["v"] = "sbcp99"
    assert audit_signing.payload_problems(payload)


# --- through the API --------------------------------------------------------


def test_api_reports_signature_status_on_create_and_list(
    client, db_session, signing_key
):
    _chain(db_session)

    r = client.post("/api/document-audits/chain/checkpoints", json={"note": "api"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["signature_status"] == "valid"
    assert body["signature_key_id"] == "test-key-1"
    assert body["signature_algorithm"] == "HMAC-SHA256"

    listed = client.get("/api/document-audits/chain/checkpoints").json()
    assert listed[0]["signature_status"] == "valid"


def test_api_reports_unsigned_when_no_key_is_configured(
    client, db_session, no_signing_key
):
    _chain(db_session)
    body = client.post(
        "/api/document-audits/chain/checkpoints", json={"note": "no key"}
    ).json()
    assert body["signature"] is None
    assert body["signature_status"] == "unsigned"


def test_api_export_and_verify_artifact_round_trip(
    client, db_session, seed_accounts, signing_key
):
    emp = client.post(
        "/api/employees",
        json={
            "first_name": "Cyn",
            "last_name": "Checkpoint",
            "pay_type": "hourly",
            "pay_rate": 25,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "WA",
        },
    ).json()
    run = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-05-15",
            "period_end": "2026-05-15",
            "pay_date": "2026-05-15",
            "stubs": [{"employee_id": emp["id"], "hours": 80}],
        },
    ).json()
    client.post(f"/api/payroll/{run['id']}/process")
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")

    cp = client.post("/api/document-audits/chain/checkpoints", json={"note": "close"})
    assert cp.status_code == 201, cp.text
    cp_id = cp.json()["id"]

    exported = client.get(f"/api/document-audits/chain/checkpoints/{cp_id}/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    artifact = exported.json()

    verified = client.post(
        "/api/document-audits/chain/checkpoints/verify-artifact", json=artifact
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["ok"] is True

    # Now delete every checkpoint row and re-verify from the artifact alone.
    from app.models.document_audit import AuditCheckpoint

    db_session.query(AuditCheckpoint).delete()
    db_session.commit()

    again = client.post(
        "/api/document-audits/chain/checkpoints/verify-artifact", json=artifact
    ).json()
    assert again["checkpoint_row_present"] is False
    assert again["signature"]["ok"] is True


def test_api_rejects_a_malformed_artifact_with_400(client, signing_key):
    r = client.post(
        "/api/document-audits/chain/checkpoints/verify-artifact",
        json={"payload": {"tip_audit_id": 1}},
    )
    assert r.status_code == 400
    assert "malformed artifact" in r.json()["detail"]


def test_export_of_a_missing_checkpoint_is_404(client, signing_key):
    assert (
        client.get("/api/document-audits/chain/checkpoints/9999/export").status_code
        == 404
    )


# --- schema ----------------------------------------------------------------


def test_signature_column_is_wide_enough(db_session):
    from app.models.document_audit import AuditCheckpoint

    assert AuditCheckpoint.__table__.columns["signature"].type.length >= 64
