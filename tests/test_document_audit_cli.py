"""Exercise the operator CLI against an isolated database, not service mocks."""

import json
import sys

import pytest

from app.models.document_audit import DocumentAudit
from app.services import document_audit as audit


@pytest.fixture
def audit_cli(db_session, monkeypatch, capsys):
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", "synthetic-cli-key")
    monkeypatch.delenv("AUDIT_CHECKPOINT_SIGNING_SECRET_PREV", raising=False)

    def run(*args, code=0):
        monkeypatch.setattr(sys, "argv", ["document_audit", *map(str, args)])
        with pytest.raises(SystemExit) as result:
            audit._cli()
        assert result.value.code == code
        return capsys.readouterr()

    return run


def seed_chain(db):
    audit.record_doc_audit(db, "test", "cli-document", "a" * 64)


def test_cli_requires_command(audit_cli):
    assert "verify-artifact" in audit_cli(code=2).out


def test_cli_verify_detects_tampering(audit_cli, db_session):
    seed_chain(db_session)
    assert json.loads(audit_cli("verify").out)["ok"] is True
    row = db_session.query(DocumentAudit).one()
    row.content_hash = "b" * 64
    db_session.commit()
    assert json.loads(audit_cli("verify", code=1).out)["ok"] is False


def test_cli_checkpoint_rejects_empty_chain(audit_cli):
    assert "error:" in audit_cli("checkpoint", code=1).err


@pytest.mark.parametrize("to_file", [False, True])
def test_cli_checkpoint_export_and_verify(audit_cli, db_session, tmp_path, to_file):
    seed_chain(db_session)
    artifact_path = tmp_path / "checkpoint.json"
    args = ["checkpoint", "--note", "synthetic operator checkpoint"]
    if to_file:
        args += ["--export", artifact_path]
    result = audit_cli(*args)
    artifact = json.loads(artifact_path.read_text() if to_file else result.out)
    assert artifact["artifact"] == "slowbooks-audit-checkpoint"
    # Exercise both export destinations independently of checkpoint creation.
    stdout = audit_cli("export", 1)
    exported = json.loads(stdout.out)
    assert exported.pop("exported_at")
    assert artifact.pop("exported_at")
    assert exported == artifact
    audit_cli("export", 1, "--out", artifact_path)
    exported = json.loads(artifact_path.read_text())
    assert exported.pop("exported_at")
    assert exported == artifact
    assert json.loads(audit_cli("verify-artifact", artifact_path).out)["ok"]
    row = db_session.query(DocumentAudit).one()
    row.content_hash = "c" * 64
    db_session.commit()
    assert not json.loads(audit_cli("verify-artifact", artifact_path, code=1).out)["ok"]


def test_cli_unsigned_checkpoint_warns_and_fails(audit_cli, db_session, monkeypatch):
    seed_chain(db_session)
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", "")
    result = audit_cli("checkpoint", code=1)
    assert "UNSIGNED" in result.err
    assert json.loads(result.out)["artifact"] == "slowbooks-audit-checkpoint"


def test_cli_missing_checkpoint(audit_cli):
    assert "no checkpoint #999" in audit_cli("export", 999, code=1).err


def test_cli_malformed_artifact(audit_cli, tmp_path):
    artifact_path = tmp_path / "bad.json"
    artifact_path.write_text("{}")
    assert (
        "malformed artifact" in audit_cli("verify-artifact", artifact_path, code=2).err
    )


def test_cli_resign_requires_key(audit_cli, monkeypatch):
    assert json.loads(audit_cli("resign").out)["checked"] == 0
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_SECRET", "")
    assert "error" in json.loads(audit_cli("resign", code=1).out)


def test_cli_resign_refuses_tampered_checkpoint(audit_cli, db_session):
    seed_chain(db_session)
    checkpoint = audit.create_checkpoint(db_session, note="original")
    assert json.loads(audit_cli("resign").out)["already_current"] == 1
    checkpoint.note = "tampered"
    db_session.commit()
    original_signature = checkpoint.signature
    assert json.loads(audit_cli("resign", code=1).out)["invalid"] == 1
    db_session.refresh(checkpoint)
    assert checkpoint.signature == original_signature


def test_changed_checkpoint_tip_is_reported(db_session, audit_cli):
    seed_chain(db_session)
    checkpoint = audit.create_checkpoint(db_session)
    row = db_session.query(DocumentAudit).one()
    row.chain_hash = "b" * 64
    db_session.commit()
    result = audit.verify_against_checkpoint(db_session, checkpoint)
    assert not result["ok"]
    assert any("that row was altered" in problem for problem in result["problems"])


def test_limited_chain_check_is_explicit(db_session):
    seed_chain(db_session)
    audit.record_doc_audit(db_session, "test", "second", "b" * 64)
    assert audit.verify_chain(db_session, limit=1)["rows_verified"] == 1
    assert audit._iso(None) == ""
    with pytest.raises(ValueError, match="JSON object"):
        audit.verify_artifact(db_session, [])


def test_module_entrypoint_runs_verification(db_session, monkeypatch, capsys):
    import runpy

    seed_chain(db_session)
    monkeypatch.setattr(sys, "argv", ["document_audit", "verify"])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(audit.__file__, run_name="__main__")
    assert result.value.code == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
