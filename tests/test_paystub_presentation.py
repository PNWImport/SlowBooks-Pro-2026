"""Pay-stub itemization and escaped template context, without a PDF engine mockup."""

import json
from datetime import date
from decimal import Decimal

import pytest

from app.models.payroll import Employee, PayRun, PayStub
from app.services import paystub_pdf as pdf


@pytest.mark.parametrize(
    "raw", [None, "", "{bad", "[]", "{}", '{"employer_ss_tax": 20}']
)
def test_deduction_fallback(raw):
    stub = PayStub(
        detail_json=raw,
        federal_tax=10,
        state_tax=2,
        state_other_employee=1,
        ss_tax=3,
        medicare_tax=4,
        pretax_deductions=5,
        posttax_deductions=6,
    )
    lines = [
        {"label": r["label"], "amount": r["amount"]} for r in pdf._deduction_lines(stub)
    ]
    assert len(lines) == 7
    assert sum(row["amount"] for row in lines) == Decimal("31")
    assert lines[0] == {"label": "Federal Income Tax", "amount": Decimal("10")}


def test_itemization_does_not_double_count_totals_or_employer_costs():
    stub = PayStub(
        detail_json=json.dumps(
            {
                "benefit:Health": 20,
                "garnishment:child_support": 10,
                "pretax_deductions": 20,
                "posttax_deductions": 10,
                "employer_benefit:Health": 50,
                "employer_medicare": 4,
                "reimbursements": 100,
                "zero": 0,
                "other_deduction": 5,
            }
        )
    )
    assert [
        {"label": r["label"], "amount": r["amount"]}
        for r in pdf._deduction_lines(stub)
    ] == [
        {"label": "Health", "amount": Decimal("20")},
        {"label": "Garnishment Child Support", "amount": Decimal("10")},
        {"label": "Other Deduction", "amount": Decimal("5")},
    ]


@pytest.mark.parametrize("raw", [None, "bad", "[]", '{"reimbursements": 100}'])
def test_reimbursement_is_added_once(raw):
    assert pdf._addition_lines(PayStub(reimbursements=100, detail_json=raw)) == [
        {"label": "Reimbursements (non-taxable)", "amount": Decimal("100")}
    ]


def test_registered_addition_is_not_a_deduction(monkeypatch):
    monkeypatch.setitem(pdf._ADDITION_KEYS, "synthetic_addition", "Synthetic addition")
    assert pdf._addition_lines(
        PayStub(detail_json='{"synthetic_addition": 12.34}')
    ) == [{"label": "Synthetic addition", "amount": Decimal("12.34")}]
    assert pdf._addition_lines(PayStub(detail_json='{"synthetic_addition": 0}')) == []


def test_template_escapes_names_and_only_displays_last_four(monkeypatch):
    rendered = []

    def capture(html):
        rendered.append(html)
        return b"synthetic-renderer-result"

    monkeypatch.setattr(pdf, "render_pdf", capture)
    employee = Employee(
        first_name="<script>synthetic</script>",
        last_name="Employee",
        ssn_last_four="1234",
    )
    day = date(2026, 1, 15)
    run = PayRun(period_start=day, period_end=day, pay_date=day)
    stub = PayStub(
        gross_pay=100,
        net_pay=95,
        hours=4,
        regular_hours=4,
        federal_tax=10,
        reimbursements=5,
    )
    result = pdf.generate_paystub_pdf(
        stub, employee, run, {"name": "Synthetic & Company"}, {"gross": 100, "net": 95}
    )
    assert result == b"synthetic-renderer-result"
    assert len(rendered) == 1
    html = rendered[0]
    assert "<script>synthetic</script>" not in html
    assert "&lt;script&gt;synthetic&lt;/script&gt;" in html
    assert "XXX-XX-1234" in html
    assert "Synthetic &amp; Company" in html
    assert "Reimbursements (non-taxable)" in html
    assert "$100.00" in html and "$95.00" in html
