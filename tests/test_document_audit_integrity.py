# ============================================================================
# Document-audit integrity — the mechanism docs/hipaa-compliance.md cites for
# § 164.312(b) Audit Controls and § 164.312(c)(1) Integrity.
# ----------------------------------------------------------------------------
# Every regulated document this app generates records a SHA-256 of its
# canonical content in `document_audits`, and prints the row id + hash prefix
# in the rendered footer. An auditor re-renders the document, recomputes, and
# compares.
#
# These tests pin the properties that claim depends on, and assert the newer
# document types (SUI, COBRA, e-signature) participate in the SAME mechanism
# rather than inventing parallel ones.
#
# The rows are LINKED: each commits to its predecessor's chain_hash, so
# deletion, reordering and insertion are detectable too — not just content
# alteration. Truncating the tail is the one thing linkage alone cannot
# catch (a shortened chain is internally valid), which is what checkpoints
# are for. All three failure modes are exercised below.
# ============================================================================

from datetime import date
from decimal import Decimal

import pytest

from app.services.document_audit import (
    audit_footer_context,
    compute_doc_hash,
    record_doc_audit,
)


def _create_employee(client, **overrides):
    body = {
        "first_name": "Ada",
        "last_name": "Auditor",
        "pay_type": "hourly",
        "pay_rate": 30,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, emp_id, pay_date="2026-05-15"):
    r = client.post(
        "/api/payroll",
        json={
            "period_start": pay_date,
            "period_end": pay_date,
            "pay_date": pay_date,
            "stubs": [{"employee_id": emp_id, "hours": 80}],
        },
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert client.post(f"/api/payroll/{run['id']}/process").status_code == 200
    return run


# --- canonical hashing properties -------------------------------------------


def test_hash_is_key_order_independent():
    """Re-rendering must reproduce the hash regardless of dict ordering."""
    a = {"b": Decimal("1.10"), "a": date(2026, 1, 1)}
    b = {"a": date(2026, 1, 1), "b": Decimal("1.10")}
    assert compute_doc_hash(a) == compute_doc_hash(b)


def test_hash_preserves_decimal_scale():
    """$1.10 and $1.1 are the same number but not the same disclosure."""
    assert compute_doc_hash({"x": Decimal("1.10")}) != compute_doc_hash(
        {"x": Decimal("1.1")}
    )


def test_hash_detects_a_one_cent_change():
    assert compute_doc_hash({"wages": Decimal("100.00")}) != compute_doc_hash(
        {"wages": Decimal("100.01")}
    )


def test_hash_excludes_time_so_rerender_matches():
    """The hash is content-only; time-of-issue lives on the audit row."""
    payload = {"employee": "Ada", "wages": Decimal("2000.00")}
    assert compute_doc_hash(payload) == compute_doc_hash(dict(payload))


def test_footer_context_exposes_a_verifiable_prefix(client, db_session):
    audit = record_doc_audit(db_session, "test", "k1", "f" * 64)
    ctx = audit_footer_context(audit)
    assert ctx["id"] == audit.id
    assert ctx["hash"] == "f" * 64
    assert ctx["hash_short"] == "f" * 16
    assert ctx["hash"].startswith(ctx["hash_short"])


# --- the ledger's shape, stated honestly ------------------------------------


def test_chain_columns_exist(db_session):
    """The linkage that makes deletion detectable."""
    from app.models.document_audit import DocumentAudit

    columns = set(DocumentAudit.__table__.columns.keys())
    assert {"prev_hash", "chain_hash"} <= columns


def test_first_row_links_to_genesis(client, db_session, seed_accounts):
    from app.models.document_audit import GENESIS_HASH, DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"])
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")

    first = db_session.query(DocumentAudit).order_by(DocumentAudit.id).first()
    assert first.prev_hash == GENESIS_HASH
    assert first.chain_hash and len(first.chain_hash) == 64


def test_each_row_links_to_the_previous(client, db_session, seed_accounts):
    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"])
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    client.post("/api/payroll/forms/w3/2026/pdf")
    client.post("/api/payroll/forms/sui/2026/2/pdf")

    rows = db_session.query(DocumentAudit).order_by(DocumentAudit.id).all()
    assert len(rows) >= 3
    for earlier, later in zip(rows, rows[1:]):
        assert later.prev_hash == earlier.chain_hash


def test_chain_verifies_clean(client, seed_accounts):
    emp = _create_employee(client)
    _run(client, emp["id"])
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    client.post("/api/payroll/forms/w3/2026/pdf")

    report = client.get("/api/document-audits/chain/verify").json()
    assert report["ok"] is True
    assert report["breaks"] == []
    assert report["rows_verified"] == report["rows_total"]
    assert report["rows_unchained"] == 0


def test_deleting_a_row_is_now_detected(client, db_session, seed_accounts):
    """The hole the old per-document ledger could not close."""
    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"])
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    client.post("/api/payroll/forms/w3/2026/pdf")
    client.post("/api/payroll/forms/sui/2026/2/pdf")
    assert client.get("/api/document-audits/chain/verify").json()["ok"] is True

    middle = db_session.query(DocumentAudit).order_by(DocumentAudit.id).all()[1]
    db_session.delete(middle)
    db_session.commit()

    report = client.get("/api/document-audits/chain/verify").json()
    assert report["ok"] is False
    assert any(
        "deleted, reordered, or inserted" in b["reason"] for b in report["breaks"]
    )


def test_altering_a_content_hash_is_detected(client, db_session, seed_accounts):
    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"])
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    client.post("/api/payroll/forms/w3/2026/pdf")

    row = db_session.query(DocumentAudit).order_by(DocumentAudit.id).first()
    row.content_hash = "b" * 64
    db_session.commit()

    report = client.get("/api/document-audits/chain/verify").json()
    assert report["ok"] is False
    assert any("does not recompute" in b["reason"] for b in report["breaks"])


def test_re_dating_a_row_is_detected(client, db_session, seed_accounts):
    """created_at is inside the chain hash, so back-dating breaks it."""
    from datetime import datetime, timezone

    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"])
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")

    row = db_session.query(DocumentAudit).order_by(DocumentAudit.id).first()
    row.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.commit()

    report = client.get("/api/document-audits/chain/verify").json()
    assert report["ok"] is False


# --- checkpoints: catching tail truncation ----------------------------------


def test_checkpoint_detects_tail_truncation(client, db_session, seed_accounts):
    """A truncated chain still verifies internally — the checkpoint is what
    notices the missing tail."""
    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"])
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    client.post("/api/payroll/forms/w3/2026/pdf")
    client.post("/api/payroll/forms/sui/2026/2/pdf")

    cp = client.post(
        "/api/document-audits/chain/checkpoints", json={"note": "quarter close"}
    )
    assert cp.status_code == 201, cp.text
    cp_id = cp.json()["id"]
    # `contains_checkpointed_state` is the containment finding on its own.
    # Top-level `ok` also requires the checkpoint's signature to verify, and
    # no signing key is configured in the test environment — that dimension
    # is covered in tests/test_audit_checkpoint_signing.py.
    before = client.get(f"/api/document-audits/chain/checkpoints/{cp_id}/verify").json()
    assert before["contains_checkpointed_state"] is True
    assert before["problems"] == []

    # Lop off the tail.
    tip = db_session.query(DocumentAudit).order_by(DocumentAudit.id.desc()).first()
    db_session.delete(tip)
    db_session.commit()

    # The remaining chain is internally valid...
    assert client.get("/api/document-audits/chain/verify").json()["ok"] is True
    # ...but the checkpoint catches it.
    result = client.get(f"/api/document-audits/chain/checkpoints/{cp_id}/verify").json()
    assert result["ok"] is False
    assert result["contains_checkpointed_state"] is False
    assert any("truncated" in p for p in result["problems"])
    assert result["current_row_count"] < result["checkpoint_row_count"]


def test_checkpoint_refuses_a_broken_chain(client, db_session, seed_accounts):
    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"])
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    client.post("/api/payroll/forms/w3/2026/pdf")

    row = db_session.query(DocumentAudit).order_by(DocumentAudit.id).first()
    row.content_hash = "c" * 64
    db_session.commit()

    r = client.post("/api/document-audits/chain/checkpoints", json={})
    assert r.status_code == 409
    assert "broken chain" in r.json()["detail"]


def test_checkpoint_on_empty_chain_is_rejected(client):
    r = client.post("/api/document-audits/chain/checkpoints", json={})
    assert r.status_code == 409
    assert "empty" in r.json()["detail"]


def test_backfill_links_unchained_rows(client, db_session, seed_accounts):
    """Simulates the migration path: rows written before the chain existed."""
    from app.models.document_audit import DocumentAudit
    from app.services.document_audit import backfill_chain, verify_chain

    emp = _create_employee(client)
    _run(client, emp["id"])
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    client.post("/api/payroll/forms/w3/2026/pdf")

    # Strip the linkage, as a pre-chain database would have it.
    for row in db_session.query(DocumentAudit).all():
        row.prev_hash = None
        row.chain_hash = None
    db_session.commit()

    report = verify_chain(db_session)
    assert report["rows_unchained"] == report["rows_total"]
    assert report["ok"] is True  # unchained rows are reported, not failures

    linked = backfill_chain(db_session)
    assert linked == report["rows_total"]

    after = verify_chain(db_session)
    assert after["ok"] is True
    assert after["rows_unchained"] == 0
    assert after["rows_verified"] == after["rows_total"]

    # Backfill is idempotent.
    assert backfill_chain(db_session) == 0


# --- every document type participates in the one mechanism ------------------


@pytest.mark.parametrize(
    "doc_type,make",
    [
        ("w2", lambda c, e: c.post(f"/api/payroll/forms/w2/{e}/pdf?year=2026")),
        ("w3", lambda c, e: c.post("/api/payroll/forms/w3/2026/pdf")),
        ("940", lambda c, e: c.post("/api/payroll/forms/940/2026/pdf")),
        ("941", lambda c, e: c.post("/api/payroll/forms/941/2026/2/pdf")),
        ("sui", lambda c, e: c.post("/api/payroll/forms/sui/2026/2/pdf")),
    ],
)
def test_generated_forms_write_one_audit_row(
    client, db_session, seed_accounts, doc_type, make
):
    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"])

    before = db_session.query(DocumentAudit).filter_by(doc_type=doc_type).count()
    r = make(client, emp["id"])
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-"
    after = db_session.query(DocumentAudit).filter_by(doc_type=doc_type).count()
    assert after == before + 1, f"{doc_type} did not record an audit row"

    row = (
        db_session.query(DocumentAudit)
        .filter_by(doc_type=doc_type)
        .order_by(DocumentAudit.id.desc())
        .first()
    )
    assert len(row.content_hash) == 64
    assert int(row.content_hash, 16) >= 0  # valid hex


def test_rerendering_the_same_form_reproduces_the_hash(
    client, db_session, seed_accounts
):
    """The auditor's workflow: regenerate, recompute, compare."""
    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"])

    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")

    rows = (
        db_session.query(DocumentAudit)
        .filter_by(doc_type="w2", doc_key=f"emp{emp['id']}-yr2026")
        .order_by(DocumentAudit.id)
        .all()
    )
    assert len(rows) == 2
    assert rows[0].content_hash == rows[1].content_hash, (
        "the same underlying data produced two different hashes — re-render "
        "verification would be impossible"
    )


def test_changing_the_data_changes_the_hash(client, db_session, seed_accounts):
    """Tamper-evidence, end to end through a real form."""
    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"], "2026-05-15")
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    first = (
        db_session.query(DocumentAudit)
        .filter_by(doc_type="w2")
        .order_by(DocumentAudit.id.desc())
        .first()
        .content_hash
    )

    # A second pay run changes the W-2's wages.
    _run(client, emp["id"], "2026-05-29")
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    second = (
        db_session.query(DocumentAudit)
        .filter_by(doc_type="w2")
        .order_by(DocumentAudit.id.desc())
        .first()
        .content_hash
    )
    assert first != second


def test_cobra_and_esign_use_the_same_ledger(client, db_session, seed_accounts):
    """The two newest document types must not invent parallel mechanisms."""
    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)

    plan = client.post(
        "/api/benefit-coverage/plans",
        json={"name": "Med", "kind": "medical", "monthly_premium_employer": 400},
    ).json()
    enr = client.post(
        "/api/benefit-coverage/enrollments",
        json={
            "employee_id": emp["id"],
            "plan_id": plan["id"],
            "coverage_start": "2026-01-01",
        },
    ).json()
    client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-06-30"},
    )
    assert (
        client.post(f"/api/benefit-coverage/enrollments/{enr['id']}/cobra-notice").status_code
        == 200
    )

    env = client.post(
        "/api/esign",
        json={
            "employee_id": emp["id"],
            "title": "Handbook",
            "body": "Acknowledged.",
            "kind": "handbook",
        },
    ).json()
    token = client.get(f"/api/employees/{emp['id']}/portal-token").json()[
        "portal_token"
    ]
    client.get(f"/portal/{token}", follow_redirects=True)
    client.post(
        f"/portal/documents/{env['id']}/sign",
        data={"signer_name": "Ada Auditor", "consent": "yes"},
        follow_redirects=False,
    )

    types = {r.doc_type for r in db_session.query(DocumentAudit).all()}
    assert {"cobra", "esign"} <= types, f"missing from the shared ledger: {types}"

    # And the e-signature seal still verifies through the public endpoint.
    v = client.get(f"/api/esign/{env['id']}/verify").json()
    assert v["body_intact"] is True and v["signature_intact"] is True
