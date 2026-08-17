# ============================================================================
# Blind indexes over the encrypted enrollment metadata.
# ----------------------------------------------------------------------------
# b3c4d5e6f7a1 encrypted the dependent identifiers and the carrier name but
# left plan kind and the coverage window in plaintext, so an attacker with
# table access could still read which employees held medical coverage over
# which months. Both are encrypted now, which breaks SQL filtering — hence the
# blind index on `kind` (equality) and nothing on the dates (their only SQL
# predicate is IS NULL, which survives encryption).
#
# Two failure modes matter more than the happy path, so both get tests:
#   * the plaintext must actually be gone from the table (read with raw SQL,
#     bypassing the ORM type)
#   * the ACA derivation must still find the enrollments. A filter left
#     comparing the encrypted column would return NOTHING and look like "no
#     employee had coverage" rather than like a bug — the worst possible
#     failure for a filing.
# ============================================================================

from datetime import date

import pytest
import sqlalchemy as sa

from app.models.benefits import BenefitKind, plan_kind_index
from app.services.blind_index import (
    INDEX_LENGTH,
    blind_index,
    normalize,
    registered_indexes,
    reindex_all,
)


def _raw(db_session, table, column, row_id):
    return db_session.execute(
        sa.text(f"SELECT {column} FROM {table} WHERE id = :i"), {"i": row_id}
    ).scalar()


def _employee(client, **overrides):
    body = {
        "first_name": "Bea",
        "last_name": "Covered",
        "pay_type": "salary",
        "pay_rate": 70000,
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
        "monthly_premium_employee": 100,
        "monthly_premium_employer": 400,
    }
    body.update(overrides)
    r = client.post("/api/benefits/plans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _enroll(client, emp_id, plan_id, start="2026-01-01"):
    r = client.post(
        "/api/benefits/enrollments",
        json={"employee_id": emp_id, "plan_id": plan_id, "coverage_start": start},
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- the primitive ----------------------------------------------------------


def test_index_is_deterministic():
    assert blind_index("t.c", "medical") == blind_index("t.c", "medical")


def test_index_is_domain_separated():
    """Without this, an attacker who cannot read either column could still
    tell that two columns in different tables hold the same value."""
    assert blind_index("a.kind", "medical") != blind_index("b.kind", "medical")


def test_index_distinguishes_different_values():
    assert blind_index("t.c", "medical") != blind_index("t.c", "dental")


def test_index_is_full_length_hex():
    value = blind_index("t.c", "medical")
    assert len(value) == INDEX_LENGTH
    assert int(value, 16) >= 0


def test_index_of_nothing_is_none():
    """A NULL plaintext must give a NULL index, so IS NULL keeps working on
    both columns."""
    assert blind_index("t.c", None) is None
    assert blind_index("t.c", "") is None
    assert blind_index("t.c", "   ") is None


@pytest.mark.parametrize(
    "a,b",
    [
        ("medical", "MEDICAL"),
        ("medical", " medical "),
        (BenefitKind.MEDICAL, "medical"),
    ],
)
def test_normalization_makes_equal_values_match(a, b):
    assert blind_index("t.c", a) == blind_index("t.c", b)


def test_normalize_renders_dates_and_enums_predictably():
    assert normalize(date(2026, 4, 2)) == "2026-04-02"
    assert normalize(BenefitKind.DENTAL) == "dental"
    assert normalize(True) == "true"


def test_index_changes_with_the_key(monkeypatch):
    """Rotating the index secret must produce different hashes, or 'rotation'
    would be a no-op that looks like it worked."""
    before = blind_index("t.c", "medical")
    monkeypatch.setenv("PAYROLL_BLIND_INDEX_SECRET", "a-different-index-key")
    assert blind_index("t.c", "medical") != before


def test_derived_index_key_is_coupled_to_the_encryption_secret(monkeypatch):
    """Pins a real operational hazard rather than leaving it implicit.

    With PAYROLL_BLIND_INDEX_SECRET unset the index key is DERIVED from
    PAYROLL_ENCRYPTION_SECRET, so rotating the encryption secret silently
    changes every index too — and a stale index makes the ACA query return
    nothing, which reads as "nobody had coverage". docs/operations.md says to
    run `reindex` after `rewrap` for exactly this reason. Setting an explicit
    index secret decouples them.
    """
    from app.services import blind_index as bi

    monkeypatch.delenv("PAYROLL_BLIND_INDEX_SECRET", raising=False)
    before = blind_index("t.c", "medical")
    monkeypatch.setattr(bi, "PAYROLL_ENCRYPTION_SECRET", "a-rotated-encryption-secret")
    assert blind_index("t.c", "medical") != before

    # With an explicit index secret, the encryption secret no longer matters.
    monkeypatch.setenv("PAYROLL_BLIND_INDEX_SECRET", "an-independent-index-key")
    pinned = blind_index("t.c", "medical")
    monkeypatch.setattr(bi, "PAYROLL_ENCRYPTION_SECRET", "rotated-again")
    assert blind_index("t.c", "medical") == pinned


def test_index_key_is_not_the_encryption_key(monkeypatch):
    """Derived from it by default, but not equal to it: leaking the index key
    must not also decrypt anything."""
    import hmac
    import hashlib

    from app.config import PAYROLL_ENCRYPTION_SECRET
    from app.services import blind_index as bi

    monkeypatch.delenv("PAYROLL_BLIND_INDEX_SECRET", raising=False)
    assert bi._index_key() != PAYROLL_ENCRYPTION_SECRET.encode("utf-8")
    # And it really is an HMAC under that derived key, not something ad hoc.
    material = f"{bi.VERSION}|t.c|medical".encode("utf-8")
    assert hmac.new(bi._index_key(), material, hashlib.sha256).hexdigest()[
        :INDEX_LENGTH
    ] == blind_index("t.c", "medical")


# --- plan kind: encrypted, queried through the index ------------------------


def test_plan_kind_is_ciphertext_in_the_database(client, db_session):
    plan = _plan(client, kind="dental")
    stored = _raw(db_session, "benefit_plans", "kind", plan["id"])
    assert stored and stored.startswith("v1:")
    assert "dental" not in stored.lower()


def test_plan_kind_round_trips_through_the_api(client):
    assert _plan(client, kind="vision")["kind"] == "vision"
    assert client.get("/api/benefits/plans").json()[0]["kind"] == "vision"


def test_plan_kind_index_is_written_on_insert(client, db_session):
    plan = _plan(client, kind="medical")
    assert _raw(
        db_session, "benefit_plans", "kind_bidx", plan["id"]
    ) == plan_kind_index(BenefitKind.MEDICAL)


def test_plan_kind_index_is_rewritten_on_update(client, db_session):
    """A mapper event, not a call-site convention — an index that one write
    path forgets silently drops the row out of every query on it."""
    from app.models.benefits import BenefitPlan

    plan = _plan(client, kind="medical")
    row = db_session.query(BenefitPlan).filter_by(id=plan["id"]).first()
    row.kind = BenefitKind.LIFE
    db_session.commit()

    assert _raw(
        db_session, "benefit_plans", "kind_bidx", plan["id"]
    ) == plan_kind_index(BenefitKind.LIFE)


def test_the_index_is_queryable_and_selective(client, db_session):
    from app.models.benefits import BenefitPlan

    _plan(client, name="Med A", kind="medical")
    _plan(client, name="Med B", kind="medical")
    _plan(client, name="Dent", kind="dental")

    medical = (
        db_session.query(BenefitPlan)
        .filter(BenefitPlan.kind_bidx == plan_kind_index(BenefitKind.MEDICAL))
        .all()
    )
    assert {p.name for p in medical} == {"Med A", "Med B"}


def test_filtering_the_encrypted_column_directly_finds_nothing(client, db_session):
    """Documents the trap the blind index exists to avoid: comparing the
    encrypted column matches no rows, quietly."""
    from app.models.benefits import BenefitPlan

    _plan(client, kind="medical")
    assert (
        db_session.query(BenefitPlan)
        .filter(BenefitPlan.kind == BenefitKind.MEDICAL)
        .count()
        == 0
    )


# --- coverage window: encrypted, no index needed ----------------------------


def test_coverage_dates_are_ciphertext(client, db_session):
    emp = _employee(client)
    plan = _plan(client)
    enr = _enroll(client, emp["id"], plan["id"], start="2026-03-01")
    client.post(
        f"/api/benefits/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-09-30"},
    )

    for column, secret in (
        ("coverage_start", "2026-03-01"),
        ("coverage_end", "2026-09-30"),
    ):
        stored = _raw(db_session, "benefit_enrollments", column, enr["id"])
        assert stored and stored.startswith("v1:")
        assert secret not in stored


def test_coverage_dates_round_trip_as_dates(client, db_session):
    from app.models.benefits import BenefitEnrollment

    emp = _employee(client)
    plan = _plan(client)
    enr = _enroll(client, emp["id"], plan["id"], start="2026-03-01")

    db_session.expire_all()
    row = db_session.query(BenefitEnrollment).filter_by(id=enr["id"]).first()
    assert row.coverage_start == date(2026, 3, 1)
    assert isinstance(row.coverage_start, date)
    assert row.coverage_end is None


def test_open_enrollment_check_still_works_on_an_encrypted_column(client):
    """`coverage_end IS NULL` needs no blind index — NULL survives
    encryption. This is the duplicate-enrollment guard that depends on it."""
    emp = _employee(client)
    plan = _plan(client)
    _enroll(client, emp["id"], plan["id"])

    duplicate = client.post(
        "/api/benefits/enrollments",
        json={
            "employee_id": emp["id"],
            "plan_id": plan["id"],
            "coverage_start": "2026-06-01",
        },
    )
    assert duplicate.status_code == 400
    assert "already has an open enrollment" in duplicate.json()["detail"]

    # Ending it frees the slot, which proves the NULL check is really reading
    # the encrypted column and not always matching.
    client.post(
        f"/api/benefits/enrollments/{emp['id']}/end",
        json={"coverage_end": "2026-05-31"},
    )


# --- the derivations that read all of it ------------------------------------


def test_the_1095_derivation_still_finds_coverage(client, seed_accounts):
    """The failure this guards against is silent: a filter left on the
    encrypted column returns zero enrollments, and an empty 1095 filing looks
    like 'nobody had coverage' rather than like a bug."""
    emp = _employee(client)
    plan = _plan(client, kind="medical")
    _enroll(client, emp["id"], plan["id"], start="2026-01-01")

    data = client.get("/api/tax-forms/1095?year=2026").json()
    assert data["form_count"] == 1
    assert data["forms"][0]["months_covered"] == list(range(1, 13))
    assert data["forms"][0]["all_12_months"] is True


def test_the_1095_derivation_still_excludes_non_medical_plans(client, seed_accounts):
    """The blind-index filter has to be selective, not just non-empty."""
    emp = _employee(client)
    dental = _plan(client, name="Dental Only", kind="dental")
    _enroll(client, emp["id"], dental["id"])

    assert client.get("/api/tax-forms/1095?year=2026").json()["form_count"] == 0


def test_the_1095_month_window_still_narrows(client, seed_accounts):
    """Range comparison on the decrypted dates, in Python — the part a blind
    index could never have answered."""
    emp = _employee(client)
    plan = _plan(client, kind="medical")
    enr = _enroll(client, emp["id"], plan["id"], start="2026-04-01")
    client.post(
        f"/api/benefits/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-07-15"},
    )

    form = client.get("/api/tax-forms/1095?year=2026").json()["forms"][0]
    assert form["months_covered"] == [4, 5, 6, 7]
    assert form["all_12_months"] is False


def test_the_cobra_notice_still_reads_plan_kind(client, seed_accounts):
    """`e.plan.kind != BenefitKind.MEDICAL` in Python on a decrypted enum."""
    emp = _employee(client)
    plan = _plan(client, kind="medical")
    enr = _enroll(client, emp["id"], plan["id"])
    client.post(
        f"/api/benefits/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-06-30"},
    )
    r = client.post(f"/api/benefits/enrollments/{enr['id']}/cobra-notice")
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-"


def test_cobra_still_refuses_a_non_medical_plan(client, seed_accounts):
    emp = _employee(client)
    plan = _plan(client, name="Eyes", kind="vision")
    enr = _enroll(client, emp["id"], plan["id"])
    client.post(
        f"/api/benefits/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-06-30"},
    )
    r = client.post(f"/api/benefits/enrollments/{enr['id']}/cobra-notice")
    assert r.status_code == 400
    assert "medical" in r.json()["detail"]


# --- rotation ---------------------------------------------------------------


def test_every_registered_index_is_known(client):
    """reindex_all can only fix what is registered."""
    assert registered_indexes()[("benefit_plans", "kind")] == "kind_bidx"


def test_the_reindex_cli_actually_sees_the_registrations(tmp_path):
    """Regression test that only a subprocess can catch.

    `python -m app.services.blind_index` loads the module as __main__, so
    importing app.models pulls in a SECOND copy under the real module name.
    The registrations land there and __main__'s registry stays empty, so
    `reindex` reported "checked: 0" and left every index stale — a silent
    no-op that looks exactly like success. In-process tests cannot see this
    because they always import the module by its real name.
    """
    import os
    import subprocess
    import sys

    db_path = tmp_path / "reindex.db"
    setup = (
        "import os;"
        f"os.environ['DATABASE_URL']='sqlite:///{db_path}';"
        "import app.models;"
        "from app.database import Base, engine, SessionLocal;"
        "Base.metadata.create_all(engine);"
        "from app.models.benefits import BenefitPlan, BenefitKind;"
        "db=SessionLocal();"
        "db.add(BenefitPlan(name='Med', kind=BenefitKind.MEDICAL));"
        "db.commit();db.close()"
    )
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "PAYROLL_BLIND_INDEX_SECRET": "seed-key",
    }
    assert subprocess.run([sys.executable, "-c", setup], env=env).returncode == 0

    # Rotate the index key, then reindex through the CLI.
    env["PAYROLL_BLIND_INDEX_SECRET"] = "rotated-key"
    result = subprocess.run(
        [sys.executable, "-m", "app.services.blind_index", "reindex"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "checked   : 1" in result.stdout, result.stdout
    assert "rewritten : 1" in result.stdout, result.stdout

    # And the row is now findable under the new key.
    check = (
        "import os;"
        f"os.environ['DATABASE_URL']='sqlite:///{db_path}';"
        "import app.models;"
        "from app.database import SessionLocal;"
        "from app.models.benefits import BenefitPlan, BenefitKind, plan_kind_index;"
        "db=SessionLocal();"
        "print(db.query(BenefitPlan).filter("
        "BenefitPlan.kind_bidx == plan_kind_index(BenefitKind.MEDICAL)).count())"
    )
    found = subprocess.run(
        [sys.executable, "-c", check], env=env, capture_output=True, text=True
    )
    assert found.stdout.strip() == "1", (found.stdout, found.stderr)


def test_reindex_rebuilds_after_an_index_key_rotation(client, db_session, monkeypatch):
    plan = _plan(client, kind="medical")
    before = _raw(db_session, "benefit_plans", "kind_bidx", plan["id"])

    monkeypatch.setenv("PAYROLL_BLIND_INDEX_SECRET", "rotated-index-key")
    # Stale until reindexed — the query would miss the row.
    assert before != plan_kind_index(BenefitKind.MEDICAL)

    report = reindex_all(db_session)
    assert report["rewritten"] == 1
    assert report["failed"] == 0
    assert _raw(
        db_session, "benefit_plans", "kind_bidx", plan["id"]
    ) == plan_kind_index(BenefitKind.MEDICAL)


def test_reindex_is_idempotent(client, db_session):
    _plan(client, kind="medical")
    first = reindex_all(db_session)
    assert first["unchanged"] == first["checked"]
    assert first["rewritten"] == 0


def test_reindex_dry_run_changes_nothing(client, db_session, monkeypatch):
    plan = _plan(client, kind="medical")
    before = _raw(db_session, "benefit_plans", "kind_bidx", plan["id"])
    monkeypatch.setenv("PAYROLL_BLIND_INDEX_SECRET", "another-index-key")

    report = reindex_all(db_session, dry_run=True)
    assert report["rewritten"] == 1
    assert _raw(db_session, "benefit_plans", "kind_bidx", plan["id"]) == before


def test_reindex_refuses_to_null_an_undecryptable_index(client, db_session):
    """A row whose plaintext will not decrypt must keep its old index. Writing
    NULL would hide it from every query that filters on the index, silently."""
    plan = _plan(client, kind="medical")
    db_session.execute(
        sa.text("UPDATE benefit_plans SET kind = :v WHERE id = :i"),
        {"v": "v1:not-valid-fernet-ciphertext", "i": plan["id"]},
    )
    db_session.commit()
    db_session.expire_all()

    report = reindex_all(db_session)
    assert report["failed"] == 1
    assert _raw(db_session, "benefit_plans", "kind_bidx", plan["id"]) is not None


# --- key rotation of the ENCRYPTION key still covers the new columns --------


def test_rewrap_covers_the_new_encrypted_columns(client, db_session):
    from app.services import encryption

    emp = _employee(client)
    plan = _plan(client)
    enr = _enroll(client, emp["id"], plan["id"])
    client.post(
        f"/api/benefits/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-08-31"},
    )

    report = encryption.rewrap_all(db_session, dry_run=True)
    # carrier_name is None here; kind + coverage_start + coverage_end = 3 new.
    assert report["checked"] >= 3, report
    assert report["already_current"] == report["checked"]
    assert report["failed"] == 0


def test_rewrap_reencrypts_kind_and_coverage_after_rotation(
    client, db_session, monkeypatch
):
    from app.models.benefits import BenefitEnrollment, BenefitPlan
    from app.services import encryption

    emp = _employee(client)
    plan = _plan(client, kind="dental")
    enr = _enroll(client, emp["id"], plan["id"], start="2026-02-01")
    original_kind = _raw(db_session, "benefit_plans", "kind", plan["id"])

    rotated = encryption._derive_fernet("a-brand-new-rotation-secret")
    monkeypatch.setattr(encryption, "_fernets", [rotated] + list(encryption._fernets))

    report = encryption.rewrap_all(db_session)
    assert report["failed"] == 0
    assert _raw(db_session, "benefit_plans", "kind", plan["id"]) != original_kind

    db_session.expire_all()
    assert (
        db_session.query(BenefitPlan).filter_by(id=plan["id"]).first().kind
        == BenefitKind.DENTAL
    )
    assert db_session.query(BenefitEnrollment).filter_by(
        id=enr["id"]
    ).first().coverage_start == date(2026, 2, 1)


# --- schema -----------------------------------------------------------------


@pytest.mark.parametrize(
    "table,column",
    [
        ("benefit_plans", "kind"),
        ("benefit_enrollments", "coverage_start"),
        ("benefit_enrollments", "coverage_end"),
    ],
)
def test_encrypted_columns_are_wide_enough_for_ciphertext(table, column):
    from app.database import Base

    length = Base.metadata.tables[table].columns[column].type.length
    assert length >= 255, f"{table}.{column} is only {length} chars wide"


def test_the_index_column_is_indexed():
    """An unindexed blind index turns every ACA query into a table scan."""
    from app.models.benefits import BenefitPlan

    assert BenefitPlan.__table__.columns["kind_bidx"].index is True
