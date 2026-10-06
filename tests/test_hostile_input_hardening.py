"""Garbage input is a 422, never a 500.

Found by firing every call the frontend makes at a live PostgreSQL-backed
instance. SQLite is lenient about all of this, so none of it showed in the
suite: a NUL byte, NaN or Infinity, a year of 9999 or -1, an over-long name
and a bad enum filter each became an opaque 500 (NaN additionally poisoned a
table until the row was deleted by hand).
"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import DataError

from app.main import _bad_value_handler, _number_too_large_handler


def _body(response):
    return response.json()["detail"]


@pytest.mark.parametrize("field", ["name", "company_name"])
def test_a_nul_byte_in_text_is_refused(client, field):
    body = {"name": "a\u0000b"} if field == "name" else {"name": "ok"}
    if field == "company_name":
        body["notes"] = "x\u0000"
    r = client.post("/api/customers", json=body)
    assert r.status_code == 422, r.text


def test_a_nul_byte_cannot_crash_the_login(unauthed_client):
    r = unauthed_client.post("/api/auth/login", json={"password": "pw\u0000x"})
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_amounts_are_refused(client, bad):
    raw = (
        '{"class_code": "A", "state": "WA", "rate_per_100": %s}' % bad
        if bad != "1e999"
        else '{"class_code": "A", "state": "WA", "rate_per_100": 1e999}'
    )
    r = client.post(
        "/api/workers-comp/rates",
        content=raw,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422, r.text
    # and the table is still readable (it used to answer 500 forever after)
    assert client.get("/api/workers-comp/rates").status_code == 200


@pytest.mark.parametrize("when", ["9999-12-31", "0202-01-01", "1899-12-31"])
def test_dates_outside_the_believable_window_are_refused(client, seed_accounts, when):
    customer = client.post("/api/customers", json={"name": "Dated"}).json()
    r = client.post(
        "/api/invoices",
        json={
            "customer_id": customer["id"],
            "date": when,
            "lines": [
                {"description": "x", "quantity": 1, "rate": "10", "amount": "10"}
            ],
        },
    )
    assert r.status_code == 422, r.text


def test_a_far_date_cannot_post_through_check_closing_date(
    client, db_session, seed_accounts
):
    """Belt and braces: a schema that is not a StrictModel is still covered by
    the check every posting route makes."""
    from fastapi import HTTPException

    from app.services.closing_date import check_closing_date
    from datetime import date

    for bad in (date(9999, 12, 31), date(1850, 1, 1)):
        with pytest.raises(HTTPException) as err:
            check_closing_date(db_session, bad)
        assert err.value.status_code == 422
    check_closing_date(db_session, date(2026, 6, 1))  # an ordinary date passes


@pytest.mark.parametrize(
    "path",
    [
        "/api/tax-forms/1099?year=-1",
        "/api/tax-forms/1099?year=0",
        "/api/tax-forms/1099?year=99999999999",
        "/api/payroll/forms/940/-1/pdf",
        "/api/payroll/forms/w3/0/pdf",
    ],
)
def test_an_impossible_year_or_quarter_is_a_422(client, path):
    r = client.get(path)
    assert r.status_code == 422, (path, r.status_code, r.text)
    assert "must be between" in str(_body(r))


def test_an_ordinary_year_still_works(client, seed_accounts):
    assert client.get("/api/tax-forms/1099?year=2026").status_code == 200


def _request(path="/api/x"):
    return SimpleNamespace(method="POST", url=SimpleNamespace(path=path))


def test_a_database_refusal_of_a_value_is_a_422_that_does_not_echo_it():
    exc = DataError("INSERT ...", {"name": "SECRET-VALUE"}, Exception("too long"))
    response = asyncio.run(_bad_value_handler(_request(), exc))
    assert response.status_code == 422
    assert b"SECRET-VALUE" not in response.body


def test_any_other_statement_error_is_still_a_server_error():
    from sqlalchemy.exc import StatementError

    exc = StatementError("boom", "SELECT 1", {}, Exception("a real bug"))
    with pytest.raises(StatementError):
        asyncio.run(_bad_value_handler(_request(), exc))


def test_a_number_too_large_to_quantize_is_a_422():
    response = asyncio.run(_number_too_large_handler(_request(), Exception()))
    assert response.status_code == 422
