"""Audit trails retain change metadata without duplicating protected values."""

from datetime import date

import pytest

from app.models.audit import AuditLog
from app.models.benefit_coverage import BenefitDependent, BenefitPlan, BenefitKind
from app.models.payroll import Employee
from app.models.settings import Settings
from app.models.users import User
from app.services.audit import _get_instance_dict


@pytest.mark.parametrize(
    "instance, protected",
    [
        (
            Employee(
                first_name="Synthetic",
                last_name="Worker",
                address1="PRIVATE",
                portal_token="TOKEN",
            ),
            ["address1", "portal_token"],
        ),
        (
            BenefitPlan(
                name="Synthetic", carrier_name="PRIVATE", kind=BenefitKind.MEDICAL
            ),
            ["carrier_name", "kind"],
        ),
        (
            BenefitDependent(
                name="PRIVATE", dob=date(2015, 1, 1), ssn_last_four="1234"
            ),
            ["name", "dob", "ssn_last_four"],
        ),
    ],
)
def test_snapshot_redacts_all_encrypted_types(instance, protected):
    snapshot = _get_instance_dict(instance)
    for field in protected:
        assert snapshot[field] == "***"


@pytest.mark.parametrize(
    "model, kwargs, field, before, after",
    [
        (
            Employee,
            {"first_name": "Synthetic", "last_name": "Worker"},
            "address1",
            "PRIVATE-OLD",
            "PRIVATE-NEW",
        ),
        (User, {"username": "synthetic"}, "password_hash", "HASH-OLD", "HASH-NEW"),
        (Settings, {"key": "smtp_password"}, "value", "SECRET-OLD", "SECRET-NEW"),
        (
            Employee,
            {"first_name": "Synthetic", "last_name": "Worker"},
            "portal_token",
            "TOKEN-OLD",
            "TOKEN-NEW",
        ),
    ],
)
def test_audit_redacts_insert_update_delete(
    db_session, model, kwargs, field, before, after
):
    obj = model(**kwargs, **{field: before})
    db_session.add(obj)
    db_session.commit()
    # Load old value to exercise both sides of UPDATE history.
    assert getattr(obj, field) == before
    setattr(obj, field, after)
    db_session.commit()
    db_session.delete(obj)
    db_session.commit()
    rows = (
        db_session.query(AuditLog)
        .filter_by(table_name=model.__tablename__)
        .order_by(AuditLog.id)
        .all()
    )
    assert [row.action for row in rows] == ["INSERT", "UPDATE", "DELETE"]
    assert rows[0].new_values[field] == "***"
    if field == "portal_token":
        # Since 2.18 the token is a property over a SHA-256 digest and an
        # encrypted copy: an update changes those two columns, and neither
        # holds the token itself (checked for every row below).
        assert {"portal_token_hash", "portal_token_enc"} <= set(rows[1].changed_fields)
    else:
        assert rows[1].old_values[field] == rows[1].new_values[field] == "***"
        assert field in rows[1].changed_fields
    assert rows[2].old_values[field] == "***"
    for row in rows:
        assert before not in str(row.old_values) + str(row.new_values)
        assert after not in str(row.old_values) + str(row.new_values)
        assert row.username == "system"
