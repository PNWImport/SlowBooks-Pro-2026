from decimal import Decimal

from app.services.gross_up import gross_up, gross_up_detail


def test_gross_up_zero_and_already_sufficient_bounds():
    assert gross_up(0, lambda value: value) == Decimal("0.00")
    assert gross_up(100, lambda value: value) == Decimal("100.00")


def test_gross_up_detail_reports_implied_and_explicit_withholding():
    implicit = gross_up_detail(100, lambda value: value * Decimal("0.8"))
    assert implicit["net"] == Decimal("100.00")
    assert implicit["withholding"] == implicit["gross"] - implicit["net"]
    explicit = gross_up_detail(
        100, lambda value: value - 10, taxes_of_gross=lambda value: Decimal("10")
    )
    assert explicit["withholding"] == Decimal("10.00")
