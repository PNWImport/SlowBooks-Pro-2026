"""Employer fringe classification is explicit and survives administration."""

import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
HEAD = "b7fringe2026105"
PREVIOUS = "m3heads2026105"


def _create(client, **changes):
    body = {"code": "FRINGE", "name": "Employer fringe", "kind": "benefit"}
    body.update(changes)
    return client.post("/api/benefits/codes", json=body)


@pytest.mark.parametrize("kind", ["benefit", "both"])
def test_explicit_fully_taxable_classification_round_trips(client, kind):
    response = _create(
        client,
        kind=kind,
        employer_taxable=True,
        employer_tax_treatment="fully_taxable",
    )
    assert response.status_code == 201, response.text
    code = response.json()
    assert code["employer_tax_treatment"] == "fully_taxable"
    assert code["employer_taxable"] is True
    assert client.get(f"/api/benefits/codes/{code['id']}").json() == code


def test_legacy_taxable_and_non_taxable_codes_stay_unclassified(client):
    for flag in (True, False):
        response = _create(client, code=f"LEGACY{flag}", employer_taxable=flag)
        assert response.status_code == 201, response.text
        assert response.json()["employer_tax_treatment"] is None
        assert response.json()["employer_taxable"] is flag


@pytest.mark.parametrize(
    "changes",
    [
        {"employer_taxable": False},
        {"employer_taxable": True, "kind": "deduction"},
    ],
)
def test_fully_taxable_classification_requires_an_employer_taxable_side(
    client, changes
):
    response = _create(client, employer_tax_treatment="fully_taxable", **changes)
    assert response.status_code == 400, response.text
    assert client.get("/api/benefits/codes").json() == []


def test_unknown_tax_treatment_is_rejected(client):
    response = _create(
        client, employer_taxable=True, employer_tax_treatment="group_term_life"
    )
    assert response.status_code == 422, response.text
    assert client.get("/api/benefits/codes").json() == []


def test_partial_update_classifies_existing_taxable_code_and_can_clear_it(client):
    response = _create(client, employer_taxable=True)
    assert response.status_code == 201, response.text
    url = f"/api/benefits/codes/{response.json()['id']}"
    updated = client.put(url, json={"employer_tax_treatment": "fully_taxable"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["employer_tax_treatment"] == "fully_taxable"
    assert updated.json()["employer_taxable"] is True
    cleared = client.put(url, json={"employer_tax_treatment": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["employer_tax_treatment"] is None
    assert cleared.json()["employer_taxable"] is True
    assert client.get(url).json()["employer_tax_treatment"] is None


@pytest.mark.parametrize(
    "changes", [{"employer_taxable": False}, {"kind": "deduction"}]
)
def test_invalid_partial_update_preserves_classification(client, changes):
    response = _create(
        client, employer_taxable=True, employer_tax_treatment="fully_taxable"
    )
    assert response.status_code == 201, response.text
    original = response.json()
    url = f"/api/benefits/codes/{original['id']}"
    changed = client.put(url, json=changes)
    assert changed.status_code == 400, changed.text
    assert client.get(url).json() == original
    # A deliberate change to non-taxable clears the classification atomically.
    if "employer_taxable" in changes:
        cleared = client.put(
            url, json={"employer_taxable": False, "employer_tax_treatment": None}
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["employer_taxable"] is False
        assert cleared.json()["employer_tax_treatment"] is None


def test_migration_preserves_legacy_codes_and_snapshot_rules(tmp_path, monkeypatch):
    database = tmp_path / "fringe-classification.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, PREVIOUS)
    legacy_rule = json.dumps({"employer_taxable": True, "source": "assignment"})
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benefit_codes (code, name, employer_taxable) "
            "VALUES ('GTL', 'Legacy group term life', 1), ('HEALTH', 'Health', 0)"
        )
        connection.execute(
            "INSERT INTO pay_stub_benefits "
            "(pay_stub_id, code, name, kind, category, calc_method, rule_json, "
            "employer_amount) VALUES (1, 'GTL', 'Legacy life', 'benefit', 'pretax', "
            "'fixed_amount', ?, 100)",
            (legacy_rule,),
        )
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (HEAD,)
        columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(benefit_codes)")
        }
        assert columns["employer_tax_treatment"][3] == 0  # nullable
        assert connection.execute(
            "SELECT code, employer_taxable, employer_tax_treatment "
            "FROM benefit_codes ORDER BY code"
        ).fetchall() == [("GTL", 1, None), ("HEALTH", 0, None)]
        assert connection.execute(
            "SELECT rule_json, employer_amount FROM pay_stub_benefits"
        ).fetchone() == (legacy_rule, 100)
    command.downgrade(cfg, PREVIOUS)
    with sqlite3.connect(database) as connection:
        assert "employer_tax_treatment" not in {
            row[1] for row in connection.execute("PRAGMA table_info(benefit_codes)")
        }
        assert connection.execute("SELECT count(*) FROM benefit_codes").fetchone() == (
            2,
        )
        assert connection.execute(
            "SELECT rule_json, employer_amount FROM pay_stub_benefits"
        ).fetchone() == (legacy_rule, 100)
