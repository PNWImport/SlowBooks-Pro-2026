"""Analytics period resolution and CSV response contracts; no external providers."""

import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from app.routes import analytics


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 8, 17)


@pytest.mark.parametrize(
    "period,start,label",
    [
        (None, date(2026, 8, 1), "month"),
        (" MTD ", date(2026, 8, 1), "month"),
        ("quarter", date(2026, 7, 1), "quarter"),
        ("QTD", date(2026, 7, 1), "quarter"),
        ("year", date(2026, 1, 1), "year"),
        ("YTD", date(2026, 1, 1), "year"),
        ("unknown", date(2026, 8, 1), "month"),
    ],
)
def test_named_periods_use_calendar_boundaries(monkeypatch, period, start, label):
    monkeypatch.setattr(analytics, "date", FixedDate)
    assert analytics._resolve_period(period, None, None) == (
        start,
        date(2026, 8, 17),
        label,
    )


@pytest.mark.parametrize(
    "start,end", [(date(2025, 4, 1), None), (None, date(2026, 5, 1))]
)
def test_explicit_bounds_override_named_period(monkeypatch, start, end):
    monkeypatch.setattr(analytics, "date", FixedDate)
    assert analytics._resolve_period("quarter", start, end) == (
        start or date(2026, 1, 1),
        end or date(2026, 8, 17),
        "custom",
    )


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@", "\t", "\r"])
def test_export_quotes_formula_names_and_preserves_amounts(
    authed_client, monkeypatch, trigger
):
    name = trigger + 'Synthetic,"name"'
    calls = []

    def snapshot(self, start_date, end_date):
        calls.append((start_date, end_date))
        return {
            "revenue_by_customer": {name: Decimal("12.34")},
            "revenue_trend": {"2026-01": Decimal("12.34")},
            "expenses_by_category": {name: Decimal("2.34")},
            "ar_aging": {"current": {name: Decimal("12.34")}},
            "ap_aging": {"current": {name: Decimal("2.34")}},
            "dso": Decimal("3.25"),
            "cash_forecast": [
                {
                    "date": "2026-02-01",
                    "collections": 12.34,
                    "payments": 2.34,
                    "net": 10,
                }
            ],
            "customer_profit": {name: {"revenue": Decimal("12.34")}},
        }

    monkeypatch.setattr(analytics.AnalyticsEngine, "get_dashboard", snapshot)
    response = authed_client.get(
        "/api/analytics/export.csv?start_date=2026-01-01&end_date=2026-01-31"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]
    assert calls == [(date(2026, 1, 1), date(2026, 1, 31))]
    rows = list(csv.reader(io.StringIO(response.text)))
    escaped = "'" + name
    assert ["revenue_by_customer", escaped, "", "12.34"] in rows
    assert ["expenses_by_category", escaped, "", "2.34"] in rows
    assert ["ar_aging", "current", escaped, "12.34"] in rows
    assert ["ap_aging", "current", escaped, "2.34"] in rows
    assert ["customer_profit", escaped, "", "12.34"] in rows
    assert ["cash_forecast", "2026-02-01", "net", "10.00"] in rows
    assert ["dso", "days", "", "3.25"] in rows


@pytest.mark.parametrize(
    "endpoint", ["revenue", "expenses", "cash-flow", "profitability", "export.csv"]
)
def test_empty_books_read_endpoints(authed_client, endpoint):
    response = authed_client.get("/api/analytics/" + endpoint)
    assert response.status_code == 200, response.text
    if endpoint == "export.csv":
        assert ["dso", "days", "", "0.00"] in list(
            csv.reader(io.StringIO(response.text))
        )
    elif endpoint == "profitability":
        assert response.json() == {}
    elif endpoint == "revenue":
        assert response.json()["by_customer"] == {}
    elif endpoint == "expenses":
        assert response.json()["by_category"] == {}
    else:
        assert response.json()["dso"] == 0


@pytest.mark.parametrize("days", [6, 366, "bad"])
def test_cash_forecast_rejects_invalid_horizons(authed_client, days):
    assert authed_client.get(f"/api/analytics/cash-flow?days={days}").status_code == 422


def test_pdf_route_passes_snapshot_and_dates_to_renderer(authed_client, monkeypatch):
    from app.services import pdf_service

    calls = []

    def render(dashboard, period, settings):
        calls.append((dashboard, period, settings))
        return b"synthetic-renderer-response"

    monkeypatch.setattr(pdf_service, "generate_analytics_pdf", render)
    response = authed_client.get(
        "/api/analytics/export.pdf?start_date=2026-01-01&end_date=2026-01-31"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].endswith('.pdf"')
    assert response.content == b"synthetic-renderer-response"
    assert len(calls) == 1
    dashboard, period, settings = calls[0]
    assert dashboard["revenue_by_customer"] == {}
    assert period == {"name": "custom", "start": "2026-01-01", "end": "2026-01-31"}
    assert isinstance(settings, dict)
