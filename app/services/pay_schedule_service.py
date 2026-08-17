# ============================================================================
# Pay-schedule date math — derive pay dates and cutoffs from an anchor.
# ----------------------------------------------------------------------------
# Pure functions over (frequency, anchor date): weekly/biweekly step in
# days; semi-monthly pays the anchor's day and that day +15, both capped to
# month end; monthly pays the anchor's day capped to month end. Weekend
# shifting is applied last so a shifted date never changes which PERIOD a
# pay date belongs to.
# ============================================================================

import calendar
from datetime import date, timedelta

from app.models.pay_schedules import PaySchedule, WeekendShift
from app.models.payroll import PayFrequency


def _cap_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _shift(d: date, rule: WeekendShift) -> date:
    if rule == WeekendShift.NONE:
        return d
    step = timedelta(days=-1 if rule == WeekendShift.PREVIOUS_BUSINESS_DAY else 1)
    while d.weekday() >= 5:
        d += step
    return d


def _raw_dates_from(anchor: date, frequency: PayFrequency, start: date, count: int):
    """Unshifted pay dates on/after `start`, derived from the anchor."""
    dates = []
    if frequency in (PayFrequency.WEEKLY, PayFrequency.BIWEEKLY):
        step = 7 if frequency == PayFrequency.WEEKLY else 14
        # Roll the anchor forward (or back) to the first occurrence >= start.
        delta_days = (start - anchor).days
        periods = delta_days // step
        d = anchor + timedelta(days=periods * step)
        while d < start:
            d += timedelta(days=step)
        while len(dates) < count:
            dates.append(d)
            d += timedelta(days=step)
    elif frequency == PayFrequency.SEMI_MONTHLY:
        day1 = anchor.day
        day2 = day1 + 15 if day1 <= 15 else day1 - 15
        lo, hi = sorted((day1, day2))
        y, m = start.year, start.month
        while len(dates) < count:
            for day in (lo, hi):
                d = _cap_day(y, m, day)
                if d >= start and len(dates) < count:
                    dates.append(d)
            m += 1
            if m > 12:
                m, y = 1, y + 1
    else:  # MONTHLY
        y, m = start.year, start.month
        while len(dates) < count:
            d = _cap_day(y, m, anchor.day)
            if d >= start:
                dates.append(d)
            m += 1
            if m > 12:
                m, y = 1, y + 1
    return dates


def upcoming_pay_dates(schedule: PaySchedule, start: date, count: int = 12) -> list:
    """The next `count` pay dates with cutoffs, shifted per the schedule."""
    lead = schedule.submission_lead_days or 0
    result = []
    for raw in _raw_dates_from(
        schedule.anchor_pay_date, schedule.frequency, start, count
    ):
        pay = _shift(raw, schedule.weekend_shift or WeekendShift.NONE)
        result.append(
            {
                "pay_date": pay.isoformat(),
                "unshifted_date": raw.isoformat(),
                "shifted": pay != raw,
                "submission_cutoff": (pay - timedelta(days=lead)).isoformat(),
            }
        )
    return result
