from datetime import date

import pytest

from app.services.federal_holidays import (
    _last_weekday,
    federal_tax_legal_holidays,
    add_federal_tax_business_days,
)


def test_december_last_weekday_and_sunday_inauguration_observation():
    assert _last_weekday(2026, 12, 0) == date(2026, 12, 28)
    # January 20, 2041 is Sunday; inauguration observes Monday the 21st.
    holidays = federal_tax_legal_holidays(2041)
    assert date(2041, 1, 20) not in holidays
    assert date(2041, 1, 21) in holidays


def test_business_day_increment_rejects_negative_counts():
    with pytest.raises(ValueError, match="non-negative"):
        add_federal_tax_business_days(date(2026, 1, 1), -1)
