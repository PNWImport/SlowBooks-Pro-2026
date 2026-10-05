"""Schedule C, mapping, and payroll-tax route dispatch contracts."""

from app.routes import tax, tax_forms
from app.services.tax_forms import irs1220


def test_schedule_c_defaults_csv_and_mapping_upsert(client, seed_accounts, monkeypatch):
    calls = []

    def schedule(db, start, end):
        calls.append((start, end))
        return {"income": 1, "expenses": []}

    monkeypatch.setattr(tax, "get_schedule_c_data", schedule)
    monkeypatch.setattr(tax, "export_schedule_c_csv", lambda data: "header\nvalue\n")
    assert client.get("/api/tax/schedule-c").status_code == 200
    assert client.get("/api/tax/schedule-c/csv").status_code == 200
    csv = client.get(
        "/api/tax/schedule-c/csv?start_date=2026-01-01&end_date=2026-12-31"
    )
    assert csv.status_code == 200
    # The export opens in Excel: it carries a UTF-8 byte-order mark.
    assert csv.text.lstrip("\ufeff").startswith("header")
    assert len(calls) == 3

    account_id = seed_accounts["6000"].id
    created = client.post(
        "/api/tax/mappings",
        json={"account_id": account_id, "tax_line": "Schedule C, Line 18"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["account_name"] == seed_accounts["6000"].name
    updated = client.post(
        "/api/tax/mappings",
        json={"account_id": account_id, "tax_line": "Schedule C, Line 27a"},
    )
    assert updated.status_code == 201
    assert updated.json()["tax_line"].endswith("27a")
    assert len(client.get("/api/tax/mappings").json()) == 1
    assert (
        client.post(
            "/api/tax/mappings", json={"account_id": 999999, "tax_line": "bad"}
        ).status_code
        == 404
    )


def test_tax_form_dispatch_pdf_and_error_boundaries(client, monkeypatch):
    monkeypatch.setattr(
        tax_forms.form_941, "compute_941", lambda *args: {"form": "941"}
    )
    monkeypatch.setattr(tax_forms.form_941, "generate_941_pdf", lambda *args: b"941")
    monkeypatch.setattr(
        tax_forms.form_940, "compute_940", lambda *args: {"form": "940"}
    )
    monkeypatch.setattr(tax_forms.form_940, "generate_940_pdf", lambda *args: b"940")
    monkeypatch.setattr(tax_forms.w2_w3, "compute_w3", lambda *args: {"w3": True})
    monkeypatch.setattr(tax_forms.w2_w3, "compute_all_w2", lambda *args: [])
    monkeypatch.setattr(tax_forms.w2_w3, "compute_w2", lambda *args: {"employee": 1})
    monkeypatch.setattr(tax_forms.w2_w3, "generate_w2_pdf", lambda *args: b"w2")
    monkeypatch.setattr(tax_forms.state_sui, "compute_sui", lambda *args: {"sui": True})
    monkeypatch.setattr(
        tax_forms.tax_liability,
        "compute_tax_liability",
        lambda *args: {"liability": True},
    )
    monkeypatch.setattr(tax_forms.form_1099, "compute_1096", lambda *args: {})
    monkeypatch.setattr(tax_forms.form_1099, "compute_1099_data", lambda *args: [])
    monkeypatch.setattr(
        tax_forms.form_1099, "generate_1099_nec_pdf", lambda *args: b"1099"
    )
    monkeypatch.setattr(tax_forms.form_1099, "generate_1096_pdf", lambda *args: b"1096")

    paths = [
        "/api/tax-forms/941?year=2026&quarter=1",
        "/api/tax-forms/941/pdf?year=2026&quarter=1",
        "/api/tax-forms/940?year=2026",
        "/api/tax-forms/940/pdf?year=2026",
        "/api/tax-forms/w2?year=2026",
        "/api/tax-forms/w2/1?year=2026",
        "/api/tax-forms/w2/1/pdf?year=2026",
        "/api/tax-forms/sui?year=2026&quarter=1",
        "/api/tax-forms/liability?year=2026&quarter=1",
        "/api/tax-forms/1099?year=2026",
        "/api/tax-forms/1099/1/pdf?year=2026",
        "/api/tax-forms/1096/pdf?year=2026",
    ]
    for path in paths:
        assert client.get(path).status_code == 200, path
    assert client.get("/api/tax-forms/941?year=2026&quarter=5").status_code == 400

    def missing(*args):
        raise ValueError("missing vendor")

    monkeypatch.setattr(tax_forms.form_1099, "generate_1099_nec_pdf", missing)
    assert client.get("/api/tax-forms/1099/999/pdf?year=2026").status_code == 404
    monkeypatch.setattr(irs1220, "generate_1099_fire", missing)
    assert client.get("/api/tax-forms/1099/fire?year=2026").status_code == 400
