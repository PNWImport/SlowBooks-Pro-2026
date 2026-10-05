"""Benefit administration rejects invalid changes and preserves valid records."""

from tests.test_benefits_engine import _code, _emp, _enroll


def test_code_identity_and_retirement_contract(client):
    first = _code(client, "FIRST")
    second = _code(client, "SECOND")
    url = f"/api/benefits/codes/{first['id']}"
    assert client.get("/api/benefits/codes/999999").status_code == 404
    assert client.get(url).json()["code"] == "FIRST"
    assert (
        client.post(
            "/api/benefits/codes", json={"code": "first", "name": "Duplicate"}
        ).status_code
        == 409
    )
    assert client.put(url, json={"code": "second"}).status_code == 409
    assert client.get(url).json()["code"] == "FIRST"
    renamed = client.put(url, json={"code": "renamed"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["code"] == "RENAMED"
    assert client.delete(url).status_code == 200
    active = client.get("/api/benefits/codes").json()
    assert [row["id"] for row in active] == [second["id"]]
    all_codes = client.get("/api/benefits/codes?include_inactive=true").json()
    assert {row["id"] for row in all_codes} == {first["id"], second["id"]}


def test_rate_validation_preserves_the_last_rate(client):
    code = _code(client, "RATE")
    url = f"/api/benefits/codes/{code['id']}/rates"
    rates = client.get(url).json()
    assert len(rates) == 1
    assert client.post(url, json={"employee_rate": 10}).status_code == 400
    assert client.delete(f"{url}/{rates[0]['id']}").status_code == 400
    assert client.get(url).json() == rates


def test_enrollment_rejections_update_and_delete(client):
    employee = _emp(client)
    code = _code(client, "ENROLL")
    url = "/api/benefits/enrollments"
    assert (
        client.post(
            url, json={"employee_id": 999999, "benefit_code_id": code["id"]}
        ).status_code
        == 404
    )
    assert (
        client.post(
            url, json={"employee_id": employee["id"], "benefit_code_id": 999999}
        ).status_code
        == 404
    )
    row = _enroll(client, employee["id"], code["id"])
    assert (
        client.post(
            url, json={"employee_id": employee["id"], "benefit_code_id": code["id"]}
        ).status_code
        == 409
    )
    edited = client.put(f"{url}/{row['id']}", json={"employee_rate": 12})
    assert edited.status_code == 200, edited.text
    assert edited.json()["employee_rate"] == 12
    assert client.put(f"{url}/999999", json={"employee_rate": 12}).status_code == 404
    assert client.delete(f"{url}/999999").status_code == 404
    assert client.delete(f"{url}/{row['id']}").json()["status"] == "deleted"
    assert client.get(url).json() == []
    assert client.get("/api/benefits/employee/999999/resolved").status_code == 404


def test_account_setup_idempotence_and_reversed_remittance_period(client):
    first = client.post("/api/benefits/setup-accounts")
    assert first.status_code == 200, first.text
    assert client.post("/api/benefits/setup-accounts").json() == {"created": []}
    result = client.get(
        "/api/benefits/remittance?start_date=2026-07-31&end_date=2026-07-01"
    )
    assert result.status_code == 400
    assert "before start_date" in result.json()["detail"]
