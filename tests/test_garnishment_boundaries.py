"""CCPA boundary cases that the payroll integration path cannot isolate."""

from decimal import Decimal

from app.services import garnishment as service


def _spec(order_id, kind, method="fixed", amount=0, **kwargs):
    return service.GarnishmentSpec(order_id, kind, method, amount, **kwargs)


def test_decimal_coercion_percent_requests_and_child_support_proration():
    assert service.compute_disposable_earnings("100.25", 100.5) == Decimal("0.00")

    # Two equal shares round to $500.01 against a $500.00 cap. The last
    # order must be constrained by the room remaining after the first one.
    results = service.apply_garnishments(
        1000,
        [
            _spec(
                2,
                "child_support",
                "percent_disposable",
                50.211,
                supports_secondary_family=True,
            ),
            _spec(
                1,
                "child_support",
                "percent_disposable",
                0.189,
                supports_secondary_family=True,
            ),
        ],
        weeks_in_period=0,
        federal_min_wage="7.25",
    )

    assert [result.order_id for result in results] == [1, 2]
    assert service.total_garnished(results) == Decimal("500.00")
    assert all(result.capped for result in results)
    assert "child-support cap reached" in results[1].note


def test_tax_levy_and_bankruptcy_are_only_limited_by_remaining_pay():
    levy = service.apply_garnishments(
        Decimal("100"),
        [_spec(1, "federal_levy", amount=100), _spec(2, "state_tax_levy", amount=10)],
    )
    assert [result.amount for result in levy] == [Decimal("100.00"), Decimal("0.00")]
    assert "remaining disposable" in levy[1].note

    bankruptcy = service.apply_garnishments(
        Decimal("100"), [_spec(1, "bankruptcy", amount=200)]
    )
    assert bankruptcy[0].amount == Decimal("100.00")
    assert bankruptcy[0].capped is True


def test_student_loan_aggregate_cap_and_ordinary_aggregate_backstop(monkeypatch):
    loans = service.apply_garnishments(
        Decimal("1000"),
        [_spec(1, "student_loan", amount=200), _spec(2, "student_loan", amount=200)],
    )
    assert [result.amount for result in loans] == [Decimal("150.00"), Decimal("100.00")]
    assert "15%" in loans[0].note
    assert "aggregate" in loans[1].note

    # The aggregate guard is intentionally independent of the ordinary-creditor
    # limit. A tighter aggregate policy still protects the total withholding.
    monkeypatch.setattr(service, "_CREDITOR_CAP_PERCENT", Decimal("0.50"))
    monkeypatch.setattr(service, "_NON_SUPPORT_AGGREGATE_PERCENT", Decimal("0.10"))
    creditor = service.apply_garnishments(
        Decimal("1000"), [_spec(1, "creditor", amount=300)]
    )
    assert creditor[0].amount == Decimal("100.00")
    assert "aggregate" in creditor[0].note


def test_final_backstop_and_child_support_arrears_cap(monkeypatch):
    arrears = _spec(
        1,
        "child_support",
        amount=1000,
        supports_secondary_family=True,
        in_arrears_12_weeks=True,
    )
    assert service._child_support_cap_percent(arrears) == Decimal("0.55")

    # The final invariant remains effective even if a future cap policy is
    # accidentally configured above available disposable pay.
    monkeypatch.setattr(
        service, "_child_support_cap_percent", lambda _spec: Decimal("2")
    )
    result = service.apply_garnishments(
        Decimal("100"), [_spec(2, "child_support", amount=200)]
    )
    assert result[0].amount == Decimal("100.00")
    assert "remaining disposable" in result[0].note
