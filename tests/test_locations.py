# ============================================================================
# Work-location coverage.
# ----------------------------------------------------------------------------
# Pins jurisdiction validation (state must have an engine, locality must
# resolve), assignment, and the payroll fallback chain: stub override >
# employee explicit > location > default.
# ============================================================================


def _create_employee(client, **overrides):
    body = {
        "first_name": "Pat",
        "last_name": "Worker",
        "pay_type": "hourly",
        "pay_rate": 30,
        "pay_frequency": "biweekly",
        "filing_status": "single",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _create_location(client, **overrides):
    body = {"name": "HQ", "state": "PA", "locality": "PA-PHILADELPHIA"}
    body.update(overrides)
    r = client.post("/api/locations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _draft_run(client, emp_id, stub_extra=None):
    r = client.post(
        "/api/payroll",
        json={
            "period_start": "2026-06-05",
            "period_end": "2026-06-05",
            "pay_date": "2026-06-05",
            "stubs": [{"employee_id": emp_id, "hours": 80, **(stub_extra or {})}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["stubs"][0]


def test_location_crud_and_validation(client):
    loc = _create_location(client)
    assert loc["state"] == "PA"

    # Duplicate name, unknown state, unknown locality all rejected.
    assert (
        client.post("/api/locations", json={"name": "HQ", "state": "PA"}).status_code
        == 400
    )
    assert (
        client.post("/api/locations", json={"name": "X", "state": "ZZ"}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/locations",
            json={"name": "Y", "state": "PA", "locality": "PA-NOWHERE"},
        ).status_code
        == 400
    )

    r = client.put(f"/api/locations/{loc['id']}", json={"city": "Philadelphia"})
    assert r.status_code == 200
    assert r.json()["city"] == "Philadelphia"


def test_assignment_and_roster(client):
    loc = _create_location(client, name="Philly Office")
    emp = _create_employee(client)
    r = client.post(f"/api/locations/{loc['id']}/assign/{emp['id']}")
    assert r.status_code == 200
    roster = client.get(f"/api/locations/{loc['id']}/employees").json()
    assert [e["id"] for e in roster] == [emp["id"]]
    assert client.post(f"/api/locations/999/assign/{emp['id']}").status_code == 404


def test_location_supplies_jurisdiction_fallback(client, seed_accounts):
    """An employee with NO explicit work_state/work_locality inherits the
    location's — visible in the stub's tax columns."""
    loc = _create_location(client, name="Philly 2")
    emp = _create_employee(client)  # no work_state, no locality
    client.post(f"/api/locations/{loc['id']}/assign/{emp['id']}")
    stub = _draft_run(client, emp["id"])
    assert stub["work_state"] == "PA"
    assert stub["work_locality"] == "PA-PHILADELPHIA"
    assert stub["local_tax"] > 0  # Philadelphia nonresident wage tax applied
    assert stub["state_tax"] > 0  # PA flat income tax applied


def test_explicit_employee_values_beat_location(client, seed_accounts):
    loc = _create_location(client, name="Philly 3")
    emp = _create_employee(client, work_state="TX")
    client.post(f"/api/locations/{loc['id']}/assign/{emp['id']}")
    stub = _draft_run(client, emp["id"])
    assert stub["work_state"] == "TX"
    assert stub["state_tax"] == 0  # TX has no income tax
    # Locality still falls back to the location (employee had none).
    assert stub["work_locality"] == "PA-PHILADELPHIA"


def test_stub_override_beats_everything(client, seed_accounts):
    loc = _create_location(client, name="Philly 4")
    emp = _create_employee(client)
    client.post(f"/api/locations/{loc['id']}/assign/{emp['id']}")
    stub = _draft_run(client, emp["id"], {"work_state": "WA", "work_locality": None})
    assert stub["work_state"] == "WA"


def test_no_location_no_change(client, seed_accounts):
    emp = _create_employee(client, work_state="WA")
    stub = _draft_run(client, emp["id"])
    assert stub["work_state"] == "WA"
    assert stub["work_locality"] is None
