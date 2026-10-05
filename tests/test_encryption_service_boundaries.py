from datetime import date

import pytest
from sqlalchemy import text

from app.models.bank_accounts import EmployeeBankAccount
from app.models.benefit_coverage import BenefitKind
from app.models.benefit_coverage import BenefitPlan
from app.models.payroll import Employee
from app.services import encryption


def test_active_key_chain_adds_distinct_previous_secret(monkeypatch):
    monkeypatch.setenv("PAYROLL_ENCRYPTION_SECRET_PREV", "previous-secret")
    assert len(encryption._active_fernets()) == 2


def test_empty_values_and_current_key_detection():
    assert encryption.encrypt("") is None
    assert encryption.decrypt("") is None
    assert encryption._is_encrypted_with_current("") is True


def test_encrypted_date_accepts_iso_text_and_rejects_bad_plaintext():
    column = encryption.EncryptedDate()
    stored = column.process_bind_param("2026-09-13", None)
    assert column.process_result_value(stored, None) == date(2026, 9, 13)
    assert column.process_result_value(encryption.encrypt("not-a-date"), None) is None
    assert column.process_result_value("broken ciphertext", None) is None


def test_encrypted_enum_handles_empty_members_and_invalid_plaintext():
    column = encryption.EncryptedEnum(BenefitKind)
    assert column.process_bind_param("", None) is None
    assert column.process_result_value("", None) is None
    assert column.process_result_value("broken ciphertext", None) is None
    assert column.process_result_value(encryption.encrypt("unknown"), None) is None
    stored = column.process_bind_param(BenefitKind.MEDICAL, None)
    assert column.process_result_value(stored, None) is BenefitKind.MEDICAL


def test_rewrap_counts_corrupt_raw_and_typed_columns(db_session):
    employee = Employee(first_name="Cipher", last_name="Test")
    plan = BenefitPlan(name="Corrupt plan", carrier_name="initial")
    db_session.add_all([employee, plan])
    db_session.flush()
    bank = EmployeeBankAccount(
        employee_id=employee.id,
        routing_number_enc="broken raw ciphertext",
    )
    db_session.add(bank)
    db_session.commit()
    db_session.execute(
        text("UPDATE benefit_plans SET carrier_name = :bad WHERE id = :id"),
        {"bad": "broken typed ciphertext", "id": plan.id},
    )
    db_session.commit()
    db_session.expire_all()

    result = encryption.rewrap_all(db_session, dry_run=True)
    assert result["failed"] == 2
    assert result["rewrapped"] == 0


def test_rewrap_rotates_raw_bank_ciphertext(db_session, monkeypatch):
    employee = Employee(first_name="Rotate", last_name="Raw")
    db_session.add(employee)
    db_session.flush()
    old = encryption._derive_fernet("old-raw-secret")
    new = encryption._derive_fernet("new-raw-secret")
    old_token = encryption._VERSION_PREFIX + old.encrypt(b"021000021").decode("ascii")
    bank = EmployeeBankAccount(
        employee_id=employee.id,
        routing_number_enc=old_token,
    )
    db_session.add(bank)
    db_session.commit()
    monkeypatch.setattr(encryption, "_fernets", [new, old])

    result = encryption.rewrap_all(db_session)
    assert result["rewrapped"] == 1
    stored = db_session.execute(
        text("SELECT routing_number_enc FROM employee_bank_accounts WHERE id = :id"),
        {"id": bank.id},
    ).scalar_one()
    assert stored != old_token
    assert encryption.decrypt(stored) == "021000021"


@pytest.mark.parametrize("failed,exit_code", [(0, 0), (1, 1)])
def test_rewrap_cli_reports_results_and_closes_session(
    failed, exit_code, monkeypatch, capsys
):
    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    db = FakeSession()
    monkeypatch.setattr("app.database.SessionLocal", lambda: db)
    monkeypatch.setattr(
        encryption,
        "rewrap_all",
        lambda session, dry_run=False: {
            "checked": 2,
            "already_current": 1,
            "rewrapped": 1,
            "failed": failed,
        },
    )
    monkeypatch.setattr("sys.argv", ["encryption", "rewrap", "--dry-run"])
    with pytest.raises(SystemExit) as raised:
        encryption._cli()
    assert raised.value.code == exit_code
    assert db.closed is True
    assert "dry-run, not committed" in capsys.readouterr().out


def test_rewrap_cli_requires_subcommand(monkeypatch):
    monkeypatch.setattr("sys.argv", ["encryption"])
    with pytest.raises(SystemExit) as raised:
        encryption._cli()
    assert raised.value.code == 2


def test_module_entrypoint_displays_usage_without_opening_database(monkeypatch, capsys):
    import runpy

    def unexpected_session():
        pytest.fail("CLI usage opened a database session")

    monkeypatch.setattr("app.database.SessionLocal", unexpected_session)
    monkeypatch.setattr("sys.argv", ["encryption"])
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(encryption.__file__, run_name="__main__")
    assert raised.value.code == 2
    assert "rewrap" in capsys.readouterr().out
