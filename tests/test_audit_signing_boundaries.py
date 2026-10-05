from app.services import audit_signing


def test_previous_key_rejects_duplicate_current_secret(monkeypatch):
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", "same-secret")
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET_PREV", "same-secret")
    assert audit_signing.previous_key() is None


def test_payload_problems_rejects_non_integer_numeric_fields():
    payload = audit_signing.build_payload(
        tip_audit_id=3, tip_chain_hash="abc", row_count=2, created_at="2026-01-01"
    )
    payload["tip_audit_id"] = "3"
    payload["row_count"] = 2.0
    problems = audit_signing.payload_problems(payload)
    assert "tip_audit_id must be an integer" in problems
    assert "row_count must be an integer" in problems
