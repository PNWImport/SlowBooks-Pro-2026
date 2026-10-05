"""Fixed-asset service validation and CSV defensive boundaries."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.fixed_assets import (
    DepreciationMethod,
    FixedAsset,
    FixedAssetStatus,
    FixedAssetType,
)
from app.services import fixed_assets as service


def _type(**overrides):
    values = dict(
        name="Type",
        depreciation_method=DepreciationMethod.STRAIGHT_LINE,
        effective_life_years=5,
    )
    values.update(overrides)
    return FixedAssetType(**values)


def _asset(asset_type, **overrides):
    values = dict(
        name="Asset",
        asset_number="FA-X",
        asset_type=asset_type,
        purchase_date=date(2026, 1, 1),
        purchase_price=Decimal("1200"),
        salvage_value=Decimal("0"),
        status=FixedAssetStatus.REGISTERED,
    )
    values.update(overrides)
    return FixedAsset(**values)


def test_depreciation_status_dates_caps_and_method_configuration():
    assert service._full_months_between(date(2026, 2, 2), date(2026, 2, 1)) == 0
    assert service._full_months_between(date(2026, 1, 31), date(2026, 2, 1)) == 0
    disposed = _asset(_type(), status=FixedAssetStatus.DISPOSED)
    assert service.period_depreciation(disposed, date(2026, 4, 1)) == 0
    no_elapsed = _asset(_type())
    assert service.period_depreciation(no_elapsed, date(2026, 1, 1)) == 0
    exhausted = _asset(_type(), accumulated_depreciation=1200)
    assert service.period_depreciation(exhausted, date(2026, 4, 1)) == 0
    with pytest.raises(HTTPException, match="effective life"):
        service.period_depreciation(
            _asset(_type(effective_life_years=0)), date(2026, 4, 1)
        )
    with pytest.raises(HTTPException, match="annual rate"):
        service.period_depreciation(
            _asset(
                _type(
                    depreciation_method=DepreciationMethod.DECLINING_BALANCE,
                    annual_rate=0,
                )
            ),
            date(2026, 4, 1),
        )
    declining = _asset(
        _type(
            depreciation_method=DepreciationMethod.DECLINING_BALANCE,
            annual_rate=Decimal("0.24"),
        )
    )
    assert service.period_depreciation(declining, date(2026, 2, 1)) == Decimal("24.00")


def test_asset_number_mapping_and_disposal_validation(db_session):
    persisted_type = _type()
    db_session.add(persisted_type)
    db_session.flush()
    first = FixedAsset(
        asset_number="FA-0001",
        name="Existing",
        asset_type_id=persisted_type.id,
        purchase_date=date(2026, 1, 1),
        purchase_price=1,
    )
    db_session.add(first)
    db_session.commit()
    assert service.next_asset_number(db_session) == "FA-0002"
    with pytest.raises(HTTPException, match="accumulated depreciation"):
        service._require_type_accounts(_type())
    asset = _asset(
        _type(
            asset_account_id=None,
            accumulated_depreciation_account_id=1,
            depreciation_expense_account_id=2,
        )
    )
    with pytest.raises(HTTPException, match="fixed-asset account"):
        service.dispose_asset(db_session, asset, date.today(), Decimal("0"), 1)


def test_asset_number_skips_a_collision_and_csv_unexpected_errors_rollback(
    db_session, monkeypatch
):
    asset_type = _type()
    db_session.add(asset_type)
    db_session.flush()
    db_session.add_all(
        [
            FixedAsset(
                asset_number="FA-0002",
                name="Two",
                asset_type_id=asset_type.id,
                purchase_date=date.today(),
                purchase_price=1,
            ),
        ]
    )
    db_session.commit()
    assert service.next_asset_number(db_session) == "FA-0003"
    monkeypatch.setattr(
        db_session, "flush", lambda: (_ for _ in ()).throw(RuntimeError("synthetic"))
    )
    result = service.import_assets_csv(
        db_session,
        "name,asset_type,purchase_date,purchase_price\nValid,Type,2026-01-01,1\n",
    )
    assert result == {
        "imported": 0,
        "errors": [{"row": 2, "message": "Unexpected error importing this row"}],
    }


def test_csv_import_reports_each_bad_row_and_rolls_back_unexpected(db_session):
    asset_type = _type()
    db_session.add(asset_type)
    db_session.commit()
    csv_text = "name,asset_type,purchase_date,purchase_price,salvage_value\n,Type,2026-01-01,1,0\nBadDate,Type,no,1,0\nBadAmount,Type,2026-01-01,no,0\n"
    report = service.import_assets_csv(db_session, csv_text)
    assert report["imported"] == 0 and len(report["errors"]) == 3
    with pytest.raises(HTTPException, match="CSV must include"):
        service.import_assets_csv(db_session, "name\nAsset\n")
