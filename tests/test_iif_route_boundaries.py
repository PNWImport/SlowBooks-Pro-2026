"""Exercise the HTTP boundary, not just the underlying IIF parsers."""

from datetime import date

import pytest

from app.routes import iif


@pytest.mark.parametrize(
    "section",
    ["all", "accounts", "classes", "customers", "vendors", "items", "estimates"],
)
def test_list_exports_are_downloads(client, monkeypatch, section):
    calls = []

    def export(db):
        calls.append(db)
        return "!ACCNT\tNAME\nACCNT\tSynthetic\n"

    monkeypatch.setattr(iif, f"export_{section}", export)
    response = client.get(f"/api/iif/export/{section}")
    assert response.status_code == 200
    assert len(calls) == 1
    assert response.text == "!ACCNT\tNAME\nACCNT\tSynthetic\n"
    filename = "slowbooks_export" if section == "all" else section
    assert (
        response.headers["content-disposition"]
        == f'attachment; filename="{filename}.iif"'
    )


@pytest.mark.parametrize(
    "section", ["invoices", "payments", "bills", "deposits", "sales-receipts"]
)
def test_dated_exports_validate_before_dispatch(client, monkeypatch, section):
    calls = []

    def export(db, start, end):
        calls.append((start, end))
        return "!TRNS\n"

    monkeypatch.setattr(iif, f"export_{section.replace('-', '_')}", export)
    response = client.get(
        f"/api/iif/export/{section}?date_from=2026-02-01&date_to=2026-02-28"
    )
    assert response.status_code == 200
    assert calls == [(date(2026, 2, 1), date(2026, 2, 28))]
    response = client.get(f"/api/iif/export/{section}?date_from=2026-02-30")
    assert response.status_code == (400 if section in {"invoices", "payments"} else 422)
    assert len(calls) == 1


@pytest.mark.parametrize("endpoint", ["import", "validate"])
def test_upload_rejects_non_iif(client, endpoint):
    response = client.post(f"/api/iif/{endpoint}", files={"file": ("bad.csv", b"bad")})
    assert response.status_code == 400


@pytest.mark.parametrize("endpoint", ["import", "validate"])
def test_legacy_cp1252_upload_reaches_parser(client, monkeypatch, endpoint):
    calls = []

    def parse(*args, **kwargs):
        calls.append(args[1] if endpoint == "import" else args[-1])
        return {} if endpoint == "import" else {"valid": True}

    monkeypatch.setattr(
        iif, "import_all" if endpoint == "import" else "validate_iif", parse
    )
    response = client.post(
        f"/api/iif/{endpoint}",
        files={"file": ("legacy.IIF", b"!CUST\tNAME\nCUST\tCaf\xe9\n")},
    )
    assert response.status_code == 200
    assert calls == ["!CUST\tNAME\nCUST\tCafé\n"]


def test_import_failure_rolls_back_and_hides_exception(client, db_session, monkeypatch):
    from app.models.contacts import Customer

    def fail(db, contents):
        db.add(Customer(name="Must roll back"))
        db.flush()
        raise RuntimeError("private-driver-secret")

    monkeypatch.setattr(iif, "import_all", fail)
    response = client.post(
        "/api/iif/import", files={"file": ("broken.iif", b"!CUST\n")}
    )
    assert response.status_code == 500
    assert "private-driver-secret" not in response.text
    assert db_session.query(Customer).filter_by(name="Must roll back").count() == 0
