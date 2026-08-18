# ============================================================================
# The Compliance tab's contract with its backend.
# ----------------------------------------------------------------------------
# app/static/js/compliance.js is the first UI over the audit chain, its
# checkpoints, and the off-box artifacts. tests/test_wiring.py already proves
# every path it calls resolves to a real route; these tests pin the RESPONSE
# SHAPES the page reads, which wiring cannot see.
#
# That matters more than usual here. The page's job is to make tampering
# visible, so a renamed field would not produce a visible error — it would
# render "undefined" or a blank cell next to a green heading, which is worse
# than no page at all.
#
# The page was also driven end-to-end in a real browser (chain verify,
# checkpoint create/verify/export, artifact paste-verify, and the
# delete-every-checkpoint case) before it shipped; these tests are the part
# that runs in CI.
# ============================================================================

import json
import re
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "compliance.js"


def _seed_chain(client, seed_accounts):
    emp = client.post(
        "/api/employees",
        json={
            "first_name": "Cee",
            "last_name": "Compliance",
            "pay_type": "hourly",
            "pay_rate": 30,
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
    client.post("/api/payroll/forms/w3/2026/pdf")
    return emp


# --- the page is actually registered ---------------------------------------


def test_the_page_is_wired_into_the_router_and_nav():
    """A page file nothing routes to is dead code that still passes review."""
    root = JS.parents[3]
    app_js = (root / "app" / "static" / "js" / "app.js").read_text()
    index = (root / "index.html").read_text()

    assert "'/compliance'" in app_js
    assert "CompliancePage.render()" in app_js
    assert 'href="#/compliance"' in index
    assert "/static/js/compliance.js" in index


# --- response shapes the page reads ----------------------------------------


def test_chain_verify_returns_every_field_the_status_panel_reads(client, seed_accounts):
    _seed_chain(client, seed_accounts)
    report = client.get("/api/document-audits/chain/verify").json()
    for key in ("ok", "rows_total", "rows_verified", "rows_unchained", "breaks"):
        assert key in report, f"chain verify lost {key}, which the panel renders"
    assert report["tip_audit_id"] is not None
    assert report["tip_chain_hash"]


def test_checkpoint_list_returns_the_columns_the_table_renders(client, seed_accounts):
    _seed_chain(client, seed_accounts)
    client.post("/api/document-audits/chain/checkpoints", json={"note": "ui"})
    row = client.get("/api/document-audits/chain/checkpoints").json()[0]
    for key in (
        "id",
        "created_at",
        "note",
        "tip_audit_id",
        "row_count",
        "signature_status",
        "signature_key_id",
    ):
        assert key in row, f"checkpoint list lost {key}, which the table renders"


def test_every_signature_status_has_a_badge_in_the_page():
    """The page maps each status to a badge. A status with no mapping falls
    through to a raw string next to a colour that may not match its meaning."""
    from app.services import audit_signing

    source = JS.read_text()
    match = re.search(r"signatureBadge\(status, keyId\) \{(.*?)\n    \}", source, re.S)
    assert match, "signatureBadge() moved — update this test"
    mapped = set(re.findall(r"^\s{12}(\w+):", match.group(1), re.M))

    produced = set()
    payload = audit_signing.build_payload(
        tip_audit_id=1, tip_chain_hash="a" * 64, row_count=1, created_at=None
    )
    produced.add(audit_signing.verify(payload, None)["status"])  # unsigned
    produced.add(audit_signing.verify(payload, "deadbeef")["status"])  # unverifiable
    # The remaining three come from audit_signing's own contract.
    produced |= {"valid", "valid_previous_key", "invalid"}

    assert produced <= mapped, f"unbadged signature statuses: {produced - mapped}"


def test_verdict_fields_are_present_on_both_verification_paths(
    client, db_session, seed_accounts
):
    """verdictHtml() renders the same fields for a checkpoint and an artifact,
    so both responses have to carry them."""
    _seed_chain(client, seed_accounts)
    cp_id = client.post(
        "/api/document-audits/chain/checkpoints", json={"note": "ui"}
    ).json()["id"]

    checkpoint = client.get(
        f"/api/document-audits/chain/checkpoints/{cp_id}/verify"
    ).json()
    artifact_doc = client.get(
        f"/api/document-audits/chain/checkpoints/{cp_id}/export"
    ).json()
    artifact = client.post(
        "/api/document-audits/chain/checkpoints/verify-artifact", json=artifact_doc
    ).json()

    for verdict in (checkpoint, artifact):
        for key in (
            "ok",
            "contains_checkpointed_state",
            "current_row_count",
            "checkpoint_row_count",
            "problems",
            "signature",
        ):
            assert key in verdict, f"verdict lost {key}, which the modal renders"
        assert "ok" in verdict["signature"]
    assert "checkpoint_row_present" in artifact


def test_export_downloads_as_a_file(client, seed_accounts):
    """The page links to this with `download` — a JSON body rendered inline
    instead of saved would silently break the off-box workflow."""
    _seed_chain(client, seed_accounts)
    cp_id = client.post("/api/document-audits/chain/checkpoints", json={}).json()["id"]
    r = client.get(f"/api/document-audits/chain/checkpoints/{cp_id}/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert f"slowbooks-checkpoint-{cp_id}.json" in r.headers["content-disposition"]
    json.loads(r.content)  # a real JSON document, not a stream


def test_the_ledger_rows_carry_what_the_table_shows(client, seed_accounts):
    _seed_chain(client, seed_accounts)
    row = client.get("/api/document-audits?limit=5").json()[0]
    for key in ("id", "created_at", "doc_type", "doc_key", "content_hash"):
        assert key in row
    assert "chain_hash" in row  # drives the linked / pre-chain badge


def test_hash_lookup_rejects_a_bad_hash_with_a_message(client):
    """The page toasts e.message on failure, so the detail has to be a string."""
    r = client.get("/api/document-audits/verify/not-a-hash")
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)


def test_checkpointing_a_broken_chain_is_a_409_the_page_can_toast(
    client, db_session, seed_accounts
):
    from app.models.document_audit import DocumentAudit

    _seed_chain(client, seed_accounts)
    row = db_session.query(DocumentAudit).order_by(DocumentAudit.id).first()
    row.content_hash = "b" * 64
    db_session.commit()

    r = client.post("/api/document-audits/chain/checkpoints", json={"note": "nope"})
    assert r.status_code == 409
    assert isinstance(r.json()["detail"], str)


# --- the page does not lie ---------------------------------------------------


def test_the_page_warns_when_a_checkpoint_comes_back_unsigned():
    """An unsigned checkpoint is a setup gap, not a success. If the page
    toasted plain success, an operator would believe they had protection they
    do not have."""
    source = JS.read_text()
    assert "unsigned" in source
    assert "AUDIT_CHECKPOINT_SIGNING_SECRET" in source


@pytest.mark.parametrize(
    "value", ["contains_checkpointed_state", "checkpoint_row_present"]
)
def test_the_page_reports_containment_separately_from_the_signature(value):
    """Collapsing 'unsigned' and 'tampered' into one red light would train an
    operator to ignore the light."""
    assert value in JS.read_text()
