from decimal import Decimal

from app.services.overtime import classify_period, classify_week


def test_overtime_empty_periods_and_flsa_under_threshold():
    assert classify_week([]) == {
        "regular": Decimal("0.00"),
        "overtime": Decimal("0.00"),
        "doubletime": Decimal("0.00"),
    }
    assert classify_period([])["regular"] == Decimal("0.00")
    assert classify_week([8, 8, 8], "wa")["overtime"] == Decimal("0.00")


def test_daily_rules_cover_zero_days_seventh_day_and_weekly_reconciliation():
    seventh = classify_week([8, 8, 8, 8, 8, 8, 10], "CA")
    assert seventh["overtime"] == Decimal("16.00")
    assert seventh["doubletime"] == Decimal("2.00")
    assert classify_week([0, -1, 13], "NV")["doubletime"] == Decimal("1.00")
    assert classify_week([10] * 6, "CO")["regular"] == Decimal("40.00")
    period = classify_period([[40], [8, 8]], "WA")
    assert period["regular"] == Decimal("56.00")
