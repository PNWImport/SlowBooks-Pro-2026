from decimal import Decimal

from app.services.pto_accrual import accrual_for_period, apply_accrual


def test_pto_accrual_coercion_unknown_methods_and_caps():
    assert accrual_for_period("per_hour_worked", "2", "10") == Decimal("20.00")
    assert accrual_for_period("unknown", 5) == Decimal("0.00")
    assert apply_accrual(1, 0, used=5) == Decimal("0.00")
    assert apply_accrual(10, 5, max_balance="12") == Decimal("12.00")
    assert apply_accrual(10, 5, max_balance=-1) == Decimal("0.00")
