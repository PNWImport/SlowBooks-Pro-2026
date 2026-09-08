"""U.S. legal-holiday dates used for federal tax deadlines.

The IRS treats Saturdays, Sundays, and legal holidays in the District of
Columbia as non-business days for federal tax deposits. This module models
the recurring statutory calendar; one-off holidays and future law changes
still require annual review against Publication 15.
"""

from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(
        days=(weekday - first.weekday()) % 7 + 7 * (occurrence - 1)
    )


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nominal_tax_holidays(year: int) -> set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _observed(date(year, 4, 16)),  # D.C. Emancipation Day
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Indigenous Peoples'/Columbus Day
        _observed(date(year, 11, 11)),  # Veterans Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),  # Christmas
    }

    # Inauguration Day is January 20 every fourth year beginning in 1937.
    # If it is Sunday, January 21 is the public observance; unlike the fixed
    # holidays above, a Saturday inauguration has no Friday observance.
    if year >= 1937 and (year - 1937) % 4 == 0:
        inauguration = date(year, 1, 20)
        if inauguration.weekday() == 6:
            inauguration += timedelta(days=1)
        holidays.add(inauguration)
    return holidays


def federal_tax_legal_holidays(year: int) -> frozenset[date]:
    """Observed D.C. legal holidays that land in ``year``."""
    dates = set()
    for nominal_year in (year - 1, year, year + 1):
        dates.update(
            day for day in _nominal_tax_holidays(nominal_year) if day.year == year
        )
    return frozenset(dates)


def federal_reserve_holidays(year: int) -> frozenset[date]:
    """Recurring Federal Reserve Bank closure dates that land in ``year``.

    Reserve Banks remain open on the Friday before a Saturday holiday, while
    a Sunday holiday closes them on Monday. This intentionally differs from
    the D.C. legal-holiday observation used for federal tax deadlines.
    """

    def reserve_observed(day: date) -> date:
        return day + timedelta(days=1) if day.weekday() == 6 else day

    holidays = {
        reserve_observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        reserve_observed(date(year, 6, 19)),
        reserve_observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        reserve_observed(date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),
        reserve_observed(date(year, 12, 25)),
    }
    return frozenset(day for day in holidays if day.year == year)


def is_federal_tax_business_day(day: date) -> bool:
    return day.weekday() < 5 and day not in federal_tax_legal_holidays(day.year)


def next_federal_tax_business_day(day: date) -> date:
    """Return ``day`` when open, otherwise the next federal tax business day."""
    while not is_federal_tax_business_day(day):
        day += timedelta(days=1)
    return day


def add_federal_tax_business_days(day: date, count: int) -> date:
    """Advance by ``count`` business days, excluding the starting date."""
    if count < 0:
        raise ValueError("count must be non-negative")
    while count:
        day += timedelta(days=1)
        if is_federal_tax_business_day(day):
            count -= 1
    return day
