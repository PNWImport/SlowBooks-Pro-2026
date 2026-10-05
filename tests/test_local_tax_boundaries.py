import json
from decimal import Decimal

import pytest

from app.services.local_tax import engine


def test_decimal_and_bracket_boundaries():
    value = Decimal("1.25")
    assert engine._dec(value) is value
    assert engine._tax_from_brackets(Decimal("0"), []) == 0
    assert engine._tax_from_brackets(Decimal("5"), [(Decimal("10"), value)]) == 0


def test_bracket_validation_and_missing_status_schedule():
    with pytest.raises(engine.LocalTaxTableError, match="must be"):
        engine.LocalityRule(
            {"code": "BAD", "kind": "brackets", "brackets": {"single": [[0]]}},
            "test.json",
        )
    with pytest.raises(engine.LocalTaxTableError, match="start at 0"):
        engine.LocalityRule(
            {
                "code": "BAD",
                "kind": "brackets",
                "brackets": {"single": [[1, ".01"]]},
            },
            "test.json",
        )
    rule = engine.LocalityRule(
        {
            "code": "EMPTY",
            "kind": "brackets",
            "brackets": {"married": []},
        },
        "test.json",
    )
    assert rule._bracket_tax(Decimal("100"), 1, "single") == 0


def test_locality_loader_handles_missing_invalid_and_duplicate_files(
    monkeypatch, tmp_path
):
    missing = tmp_path / "missing"
    monkeypatch.setattr(engine, "LOCALITY_DIR", missing)
    engine._load.cache_clear()
    assert engine._load() == ({}, [])

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "bad.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(engine, "LOCALITY_DIR", invalid)
    engine._load.cache_clear()
    with pytest.raises(engine.LocalTaxTableError, match="invalid JSON"):
        engine._load()

    duplicate = tmp_path / "duplicate"
    duplicate.mkdir()
    payload = {
        "state": "ZZ",
        "localities": [{"code": "ZZ-ONE"}, {"code": "ZZ-ONE"}],
    }
    (duplicate / "dup.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(engine, "LOCALITY_DIR", duplicate)
    engine._load.cache_clear()
    with pytest.raises(engine.LocalTaxTableError, match="duplicate"):
        engine._load()
    engine._load.cache_clear()


def test_employer_percentage_and_flat_levies(monkeypatch):
    rule = engine.LocalityRule(
        {
            "code": "ZZ-WORK",
            "name": "Worktown",
            "resident_rate": "0",
            "employer_rate": ".01",
            "employer_flat_per_year": "26",
        },
        "test.json",
    )
    rule.verified = True
    monkeypatch.setattr(engine, "get_locality", lambda code: rule if code else None)
    result = engine.calculate_local_taxes(
        work_locality="ZZ-WORK",
        residence_locality=None,
        taxable=Decimal("1000"),
        pay_periods=26,
    )
    assert result.employer == Decimal("11.00")
    assert result.detail["Worktown (employer)"] == Decimal("10.00")
    assert result.detail["Worktown (employer, flat)"] == Decimal("1.00")
