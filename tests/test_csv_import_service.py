"""CSV imports preserve field values and reject duplicates within one upload."""

from decimal import Decimal

import pytest

from app.models.contacts import Customer, Vendor
from app.models.items import Item, ItemType
from app.services import csv_import


@pytest.fixture(params=["customers", "vendors", "items"])
def importer(request):
    return (
        getattr(csv_import, f"import_{request.param}"),
        {"customers": Customer, "vendors": Vendor, "items": Item}[request.param],
    )


def test_duplicate_names_in_one_upload_are_skipped(db_session, importer):
    run, model = importer
    result = run(db_session, "Name\nRepeated\n Repeated \nOther\n")
    assert result == {"created": 2, "skipped": 1, "errors": []}
    assert sorted(row.name for row in db_session.query(model)) == ["Other", "Repeated"]


def test_existing_names_and_missing_rows(db_session, importer):
    run, model = importer
    run(db_session, "Name\nExisting\n")
    result = run(db_session, 'Name\nExisting\n" "\nNew\n')
    assert result == {"created": 1, "skipped": 1, "errors": ["Row 3: Missing name"]}
    assert db_session.query(model).count() == 2


@pytest.mark.parametrize("kind,model", [("customers", Customer), ("vendors", Vendor)])
def test_contact_fields_are_preserved(db_session, kind, model):
    result = getattr(csv_import, f"import_{kind}")(
        db_session,
        "Name,Company,Email,Phone,Address,City,State,ZIP,Terms\n"
        "-Dash Co,Example,synthetic@example.invalid,555-0100,1 Test St,Test,WA,00000,Net 15\n",
    )
    assert result == {"created": 1, "skipped": 0, "errors": []}
    row = db_session.query(model).one()
    assert (row.name, row.company, row.email, row.phone, row.terms) == (
        "-Dash Co",
        "Example",
        "synthetic@example.invalid",
        "555-0100",
        "Net 15",
    )
    prefix = "bill_" if model is Customer else ""
    assert getattr(row, prefix + "address1") == "1 Test St"
    assert getattr(row, prefix + "city") == "Test"
    assert getattr(row, prefix + "state") == "WA"
    assert getattr(row, prefix + "zip") == "00000"


@pytest.mark.parametrize("kind", ["product", "service", "material", "labor", "unknown"])
def test_item_type_and_money(db_session, kind):
    result = csv_import.import_items(
        db_session, f"Name,Type,Description,Rate,Cost\nItem,{kind},Example,12.34,5.67\n"
    )
    assert result == {"created": 1, "skipped": 0, "errors": []}
    row = db_session.query(Item).one()
    assert row.item_type == (ItemType.SERVICE if kind == "unknown" else ItemType(kind))
    assert row.rate == Decimal("12.34")
    assert row.cost == Decimal("5.67")
    assert row.description == "Example"


def test_invalid_item_row_does_not_block_valid_row(db_session):
    result = csv_import.import_items(
        db_session, "Name,Rate,Cost\nBad,not-money,1\nGood,12,5\n"
    )
    assert result == {
        "created": 1,
        "skipped": 0,
        "errors": ['Row 2: Rate "not-money" is not a number.'],
    }
    assert db_session.query(Item).one().name == "Good"


def test_failed_item_does_not_reserve_its_name(db_session):
    result = csv_import.import_items(
        db_session, "Name,Rate,Cost\nRetry,invalid,1\nRetry,12,5\n"
    )
    assert result == {
        "created": 1,
        "skipped": 0,
        "errors": ['Row 2: Rate "invalid" is not a number.'],
    }
    assert db_session.query(Item).one().rate == Decimal("12")


def test_truncated_names_are_deduplicated(db_session, importer):
    run, model = importer
    name = "N" * 200
    result = run(db_session, f"Name\n{name}A\n{name}B\n")
    assert result == {"created": 1, "skipped": 1, "errors": []}
    assert db_session.query(model).one().name == name


def test_short_csv_row_reports_error_and_continues(db_session, importer):
    run, model = importer
    result = run(db_session, "Company,Name\nMissing column\nExample,Good\n")
    assert result == {"created": 1, "skipped": 0, "errors": ["Row 2: Missing name"]}
    assert db_session.query(model).one().name == "Good"
