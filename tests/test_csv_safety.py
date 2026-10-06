"""
CSV formula-injection protection: any user-controlled cell that starts
with =, +, -, @, \\t, or \\r must be prefixed with a single quote before
being written to the CSV stream.
"""

import pytest

from app.routes.analytics import _csv_safe


@pytest.mark.parametrize(
    "dangerous",
    [
        "=SUM(A1:A2)",
        "+1+1",
        "-2+3",
        "@cmd",
        "\tHELLO",
        "\rEVIL",
        '=HYPERLINK("http://evil.com")',
    ],
)
def test_csv_safe_neutralizes_formula_prefix(dangerous):
    safe = _csv_safe(dangerous)
    assert safe.startswith("'")
    assert safe[1:] == dangerous


@pytest.mark.parametrize(
    "benign",
    [
        "ABC Corp",
        "January 2026",
        "1234.56",
        "hello world",
        "",
    ],
)
def test_csv_safe_passes_benign_unchanged(benign):
    assert _csv_safe(benign) == benign


def test_csv_safe_handles_none():
    # None gets stringified ("None") — not dangerous, not formula-prefix,
    # passes through unchanged. The important invariant is "no formula
    # injection", not "None becomes empty string".
    assert _csv_safe(None) == "None"


def test_schedule_c_csv_writes_a_net_loss_as_a_number_not_text():
    import csv
    import io

    from app.services.tax_export import export_schedule_c_csv

    data = {
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "lines": [
            {
                "line": "Line 1",
                "total": -5220.53,
                "accounts": [
                    {
                        "account_number": "4000",
                        "account_name": '=HYPERLINK("http://evil.example")',
                        "amount": -5220.53,
                    }
                ],
            }
        ],
        "gross_receipts": 0,
        "returns_and_allowances": 0,
        "cost_of_goods_sold": 0,
        "other_income": 0,
        "gross_income": 0,
        "total_expenses": 5220.53,
        "net_profit": -5220.53,
    }
    rows = list(csv.reader(io.StringIO(export_schedule_c_csv(data))))
    net = next(r for r in rows if r and r[0].startswith("NET PROFIT"))
    assert net[3] == "-5220.53"  # no leading apostrophe: Excel reads a number
    hostile = next(r for r in rows if r[:1] == ["Line 1"])
    assert hostile[2] == '\'=HYPERLINK("http://evil.example")'  # text still guarded
    assert hostile[3] == "-5220.53"


@pytest.mark.parametrize("text", ["-1+cmd", "+1+1", "-5220.53x", "-", "=1", "-1.2.3"])
def test_only_a_plain_signed_decimal_escapes_the_guard(text):
    from app.services.csv_export import _csv_safe as shared

    assert shared(text) == "'" + text
    assert shared("-5220.53") == "-5220.53"
    assert shared("+12") == "+12"
