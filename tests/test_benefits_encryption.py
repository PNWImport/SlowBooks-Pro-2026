# ============================================================================
# Benefits ePHI encryption at rest.
# ----------------------------------------------------------------------------
# The columns docs/hipaa-compliance.md flags as the ePHI surface — carrier
# name and every dependent identifier — are Fernet-encrypted with the same
# scheme and key as employee bank PII.
#
# The tests that matter here are the ones that read the RAW column with SQL,
# bypassing the ORM type, and assert the plaintext is not in the database. An
# encryption test that only round-trips through the ORM would pass just as
# happily if the TypeDecorator were removed.
# ============================================================================

from datetime import date

import pytest
import sqlalchemy as sa


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


def _plan(client, **overrides):
    body = {
        "name": "Gold PPO",
        "kind": "medical",
        "carrier_name": "Blue Shield of Testland",
        "monthly_premium_employee": 150,
        "monthly_premium_employer": 450,
    }
    body.update(overrides)
    r = client.post("/api/benefit-coverage/plans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _enroll(client, emp_id, plan_id, start="2026-01-01"):
    r = client.post(
        "/api/benefit-coverage/enrollments",
        json={"employee_id": emp_id, "plan_id": plan_id, "coverage_start": start},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _raw(db_session, table, column, row_id):
    """Read a column with SQL, bypassing the ORM's decryption."""
    return db_session.execute(
        sa.text(f"SELECT {column} FROM {table} WHERE id = :i"), {"i": row_id}
    ).scalar()


# --- carrier name -----------------------------------------------------------


def test_carrier_name_is_ciphertext_in_the_database(client, db_session):
    plan = _plan(client)
    stored = _raw(db_session, "benefit_plans", "carrier_name", plan["id"])
    assert stored, "carrier_name was not stored at all"
    assert "Blue Shield" not in stored
    assert stored.startswith("v1:"), "expected versioned Fernet ciphertext"


def test_carrier_name_round_trips_through_the_api(client):
    plan = _plan(client)
    assert plan["carrier_name"] == "Blue Shield of Testland"
    listed = client.get("/api/benefit-coverage/plans").json()
    assert listed[0]["carrier_name"] == "Blue Shield of Testland"


def test_null_carrier_name_stays_null(client, db_session):
    plan = _plan(client, name="No Carrier", carrier_name=None)
    assert _raw(db_session, "benefit_plans", "carrier_name", plan["id"]) is None
    assert plan["carrier_name"] is None


# --- dependent identifiers --------------------------------------------------


def test_dependent_identifiers_are_ciphertext(client, db_session):
    emp = _create_employee(client)
    plan = _plan(client)
    enr = _enroll(client, emp["id"], plan["id"])
    r = client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/dependents",
        json={
            "name": "Wilhelmina Dependent",
            "relationship_kind": "child",
            "ssn_last_four": "6789",
            "dob": "2015-04-02",
        },
    )
    assert r.status_code == 201, r.text
    dep_id = r.json()["id"]

    for column, secret in (
        ("name", "Wilhelmina"),
        ("ssn_last_four", "6789"),
        ("dob", "2015-04-02"),
    ):
        stored = _raw(db_session, "benefit_dependents", column, dep_id)
        assert stored, f"{column} not stored"
        assert secret not in stored, f"{column} leaked plaintext: {stored!r}"
        assert stored.startswith("v1:")

    # Relationship is a category, not an identifier — deliberately plaintext
    # so the 1095 covered-individuals listing can group on it.
    assert (
        _raw(db_session, "benefit_dependents", "relationship_kind", dep_id) == "child"
    )


def test_dependent_dob_round_trips_as_a_date(client, db_session):
    from app.models.benefit_coverage import BenefitDependent

    emp = _create_employee(client)
    plan = _plan(client)
    enr = _enroll(client, emp["id"], plan["id"])
    dep_id = client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/dependents",
        json={"name": "Dee Pendant", "dob": "2015-04-02"},
    ).json()["id"]

    db_session.expire_all()
    dep = db_session.query(BenefitDependent).filter_by(id=dep_id).first()
    assert dep.dob == date(2015, 4, 2)
    assert isinstance(dep.dob, date)


def test_dependent_name_reaches_the_1095_covered_individuals(client):
    """Encryption must not break the ACA derivation that reads these."""
    emp = _create_employee(client, first_name="Self")
    plan = _plan(client, name="Self-Funded", self_insured=True)
    enr = _enroll(client, emp["id"], plan["id"])
    client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/dependents",
        json={"name": "Kid Worker", "relationship_kind": "child"},
    )
    data = client.get("/api/tax-forms/1095?year=2026").json()
    names = {c["name"] for c in data["forms"][0]["covered_individuals"]}
    assert names == {"Self Worker", "Kid Worker"}


def test_carrier_name_reaches_the_cobra_notice(client):
    """The COBRA template prints the carrier — decryption must work there."""
    emp = _create_employee(client)
    plan = _plan(client)
    enr = _enroll(client, emp["id"], plan["id"])
    client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-06-30"},
    )
    r = client.post(f"/api/benefit-coverage/enrollments/{enr['id']}/cobra-notice")
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-"


# --- key rotation coverage --------------------------------------------------


def test_rewrap_covers_every_encrypted_column(client, db_session):
    """A column missing from rewrap_all survives rotation only until the
    previous key is dropped — so the coverage list is load-bearing."""
    from app.services import encryption

    emp = _create_employee(client)
    plan = _plan(client)
    enr = _enroll(client, emp["id"], plan["id"])
    client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/dependents",
        json={"name": "Rota Ted", "ssn_last_four": "1111", "dob": "2010-01-01"},
    )
    r = client.post(
        f"/api/employees/{emp['id']}/bank-accounts",
        json={"routing_number": "021000021", "account_number": "111122223333"},
    )
    assert r.status_code == 201, r.text

    report = encryption.rewrap_all(db_session, dry_run=True)
    # 2 bank fields + carrier_name + 3 dependent fields = 6 encrypted values.
    assert report["checked"] >= 6, report
    # Everything is already under the current key, so nothing needs rewrapping.
    assert report["already_current"] == report["checked"]
    assert report["failed"] == 0


def test_rewrap_reencrypts_benefit_columns_after_rotation(
    client, db_session, monkeypatch
):
    """End-to-end rotation: old key becomes PREV, new key becomes current,
    rewrap re-encrypts, and the plaintext still reads back."""
    from app.services import encryption

    emp = _create_employee(client)
    plan = _plan(client)
    enr = _enroll(client, emp["id"], plan["id"])
    client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/dependents",
        json={"name": "Rolled Over", "ssn_last_four": "2222"},
    )
    original = _raw(db_session, "benefit_plans", "carrier_name", plan["id"])

    # Rotate: current key moves to PREV, a new key becomes current.
    old_secret = encryption._fernets
    rotated = encryption._derive_fernet("a-brand-new-rotation-secret")
    monkeypatch.setattr(encryption, "_fernets", [rotated] + list(old_secret))

    report = encryption.rewrap_all(db_session)
    assert report["rewrapped"] >= 3, report
    assert report["failed"] == 0

    rewrapped = _raw(db_session, "benefit_plans", "carrier_name", plan["id"])
    assert rewrapped != original, "ciphertext unchanged — rewrap did nothing"

    db_session.expire_all()
    from app.models.benefit_coverage import BenefitDependent, BenefitPlan

    assert (
        db_session.query(BenefitPlan).filter_by(id=plan["id"]).first().carrier_name
        == "Blue Shield of Testland"
    )
    dep = db_session.query(BenefitDependent).first()
    assert dep.name == "Rolled Over"
    assert dep.ssn_last_four == "2222"


def test_undecryptable_value_returns_none_not_an_exception(client, db_session):
    """One unreadable row must not take down a whole ACA or payroll run."""
    from app.models.benefit_coverage import BenefitPlan

    plan = _plan(client)
    db_session.execute(
        sa.text("UPDATE benefit_plans SET carrier_name = :v WHERE id = :i"),
        {"v": "v1:this-is-not-valid-fernet-ciphertext", "i": plan["id"]},
    )
    db_session.commit()
    db_session.expire_all()

    row = db_session.query(BenefitPlan).filter_by(id=plan["id"]).first()
    assert row.carrier_name is None  # logged, not raised


@pytest.mark.parametrize("column", ["name", "ssn_last_four", "dob"])
def test_dependent_columns_are_wide_enough_for_ciphertext(column):
    """Fernet output is ~100-200 chars; a 4-char column would truncate."""
    from app.models.benefit_coverage import BenefitDependent

    length = BenefitDependent.__table__.columns[column].type.length
    assert length >= 255, f"{column} is only {length} chars wide"
