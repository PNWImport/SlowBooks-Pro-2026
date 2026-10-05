"""Check amount wording must retain cents and normalize rounding carry."""

from decimal import Decimal

import pytest

from app.services.pdf_service import _amount_to_words


@pytest.mark.parametrize(
    "amount, expected",
    [
        (None, "Zero and 00/100"),
        ("0.01", "Zero and 01/100"),
        ("19.25", "Nineteen and 25/100"),
        ("21.50", "Twenty-One and 50/100"),
        ("100.00", "One Hundred and 00/100"),
        (
            "1234567.89",
            "One Million Two Hundred Thirty-Four Thousand Five Hundred Sixty-Seven and 89/100",
        ),
        ("1.995", "Two and 00/100"),
        ("0.005", "Zero and 01/100"),
        ("-1.25", "Negative One and 25/100"),
        ("-0.25", "Negative Zero and 25/100"),
    ],
)
def test_amount_words_decimal_boundaries(amount, expected):
    assert _amount_to_words(Decimal(amount) if amount is not None else None) == expected
