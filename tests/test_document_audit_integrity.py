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
# SCOPE NOTE — this is a per-document hash ledger, NOT a linked hash chain.
# Each row stands alone: there is no prev-hash column tying row N to row N-1.
# That detects ALTERATION of a document's content (tested below) but NOT
# DELETION of an audit row. `test_ledger_has_no_linkage_between_rows` pins
# that limitation explicitly so the gap stays visible instead of being
# assumed away by the word "chain" in the surrounding docs.
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


def test_ledger_has_no_linkage_between_rows(db_session):
    """Documents the real limitation: rows are independent, not chained.

    A linked chain would let an auditor prove no row was removed. This
    ledger cannot, because nothing binds row N to row N-1. If that
    guarantee is ever added, this test is the one that should change.
    """
    from app.models.document_audit import DocumentAudit

    columns = set(DocumentAudit.__table__.columns.keys())
    assert not columns & {
        "prev_hash",
        "previous_hash",
        "chain_hash",
        "prev_id",
    }, (
        "document_audits gained linkage columns — the ledger may now be a real "
        "chain; update this test and the § 164.312(c)(1) claim in "
        "docs/hipaa-compliance.md accordingly."
    )


def test_deleting_a_row_is_undetectable_today(client, db_session, seed_accounts):
    """The concrete consequence of the above, pinned so it is not a surprise."""
    from app.models.document_audit import DocumentAudit

    emp = _create_employee(client)
    _run(client, emp["id"])
    client.post(f"/api/payroll/forms/w2/{emp['id']}/pdf?year=2026")
    client.post("/api/payroll/forms/sui/2026/2/pdf")

    rows = db_session.query(DocumentAudit).order_by(DocumentAudit.id).all()
    assert len(rows) >= 2
    surviving = [r.content_hash for r in rows[1:]]

    db_session.delete(rows[0])
    db_session.commit()

    after = db_session.query(DocumentAudit).order_by(DocumentAudit.id).all()
    # Every surviving hash still verifies — nothing about the remaining rows
    # reveals that an earlier one was removed.
    assert [r.content_hash for r in after] == surviving


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
        "/api/benefits/plans",
        json={"name": "Med", "kind": "medical", "monthly_premium_employer": 400},
    ).json()
    enr = client.post(
        "/api/benefits/enrollments",
        json={
            "employee_id": emp["id"],
            "plan_id": plan["id"],
            "coverage_start": "2026-01-01",
        },
    ).json()
    client.post(
        f"/api/benefits/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-06-30"},
    )
    assert (
        client.post(f"/api/benefits/enrollments/{enr['id']}/cobra-notice").status_code
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
