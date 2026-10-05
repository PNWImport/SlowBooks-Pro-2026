from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services import currency


def test_currency_rate_validation_and_feed_success(monkeypatch, db_session):
    monkeypatch.setattr(
        currency, "get_all_settings", lambda _db: {"home_currency": "usd"}
    )
    with pytest.raises(HTTPException, match="Exchange rate"):
        currency.resolve_rate(db_session, "eur", Decimal("0"))
    monkeypatch.setattr(
        "app.services.fx_service.get_rate", lambda *_: {"rate": Decimal("1.08")}
    )
    assert currency.resolve_rate(db_session, "eur", None) == ("EUR", Decimal("1.08"))


def test_convert_lines_adjusts_debit_drift():
    lines = currency.convert_lines(
        [{"debit": Decimal("1"), "credit": 0}, {"debit": 0, "credit": Decimal(".99")}],
        Decimal("1.005"),
    )
    assert sum(line["debit"] for line in lines) == sum(line["credit"] for line in lines)
