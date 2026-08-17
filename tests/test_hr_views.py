# ============================================================================
# Org chart, PTO calendar, performance-review coverage.
# ----------------------------------------------------------------------------
# Pins the manager-tree build (roots, nesting, cycle break-not-500),
# the calendar window overlap semantics, and the review lifecycle
# (draft-only edits, submit once, acknowledge submitted-only).
# ============================================================================


def _create_employee(client, **overrides):
    body = {
        "first_name": "Pat",
        "last_name": "Worker",
        "pay_type": "salary",
        "pay_rate": 60000,
        "pay_frequency": "biweekly",
        "filing_status": "single",
        "work_state": "WA",
    }
    body.update(overrides)
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- org chart ---------------------------------------------------------------


def test_org_chart_tree(client):
    boss = _create_employee(client, first_name="Ada", last_name="Boss")
    mid = _create_employee(
        client, first_name="Mia", last_name="Mid", manager_id=boss["id"]
    )
    _create_employee(client, first_name="Ian", last_name="IC", manager_id=mid["id"])

    chart = client.get("/api/hr/org-chart").json()
    assert chart["cycle_employee_ids"] == []
    assert len(chart["tree"]) == 1
    root = chart["tree"][0]
    assert root["name"] == "Ada Boss"
    assert root["reports"][0]["name"] == "Mia Mid"
    assert root["reports"][0]["reports"][0]["name"] == "Ian IC"


def test_org_chart_breaks_cycles(client, db_session):
    a = _create_employee(client, first_name="A", last_name="One")
    b = _create_employee(client, first_name="B", last_name="Two", manager_id=a["id"])
    # Close the loop directly (the API may not allow it, the DB does).
    from app.models.payroll import Employee

    db_session.query(Employee).filter(Employee.id == a["id"]).update(
        {"manager_id": b["id"]}
    )
    db_session.commit()

    r = client.get("/api/hr/org-chart")
    assert r.status_code == 200  # never a 500
    assert r.json()["cycle_employee_ids"] != []


def test_org_chart_excludes_inactive_by_default(client):
    emp = _create_employee(client, first_name="Gone")
    client.post(
        f"/api/employees/{emp['id']}/terminate",
        json={"termination_date": "2026-06-01", "reason": "voluntary"},
    )
    names = [n["name"] for n in client.get("/api/hr/org-chart").json()["tree"]]
    assert "Gone Worker" not in names
    names = [
        n["name"]
        for n in client.get("/api/hr/org-chart?include_inactive=true").json()["tree"]
    ]
    assert "Gone Worker" in names


# --- PTO calendar ------------------------------------------------------------


def test_pto_calendar_window_overlap(client):
    emp = _create_employee(client)
    r = client.post(
        "/api/pto/requests",
        json={
            "employee_id": emp["id"],
            "start_date": "2026-07-06",
            "end_date": "2026-07-10",
            "hours": 40,
            "pto_type": "vacation",
        },
    )
    assert r.status_code in (200, 201), r.text
    req_id = r.json()["id"]
    client.post(f"/api/pto/requests/{req_id}/approve")

    # Window overlapping the request start.
    cal = client.get("/api/hr/pto-calendar?start=2026-07-01&end=2026-07-07").json()
    assert len(cal["entries"]) == 1
    assert cal["entries"][0]["status"] == "approved"
    # Fully before / after: empty.
    assert (
        client.get("/api/hr/pto-calendar?start=2026-06-01&end=2026-06-30").json()[
            "entries"
        ]
        == []
    )
    # end before start: 400.
    assert (
        client.get("/api/hr/pto-calendar?start=2026-07-10&end=2026-07-01").status_code
        == 400
    )


# --- reviews -----------------------------------------------------------------


def test_review_lifecycle(client):
    emp = _create_employee(client)
    boss = _create_employee(client, first_name="Ada", last_name="Boss")
    r = client.post(
        "/api/hr/reviews",
        json={
            "employee_id": emp["id"],
            "reviewer_id": boss["id"],
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
            "rating": 4,
            "feedback": "Solid work",
        },
    )
    assert r.status_code == 201, r.text
    review = r.json()
    assert review["status"] == "draft"

    # Draft editable; rating bounds enforced.
    assert (
        client.put(f"/api/hr/reviews/{review['id']}", json={"rating": 5}).status_code
        == 200
    )
    assert (
        client.put(f"/api/hr/reviews/{review['id']}", json={"rating": 9}).status_code
        == 400
    )

    # Acknowledge before submit: 400. Submit; re-submit: 400.
    assert (
        client.post(f"/api/hr/reviews/{review['id']}/acknowledge", json={}).status_code
        == 400
    )
    assert client.post(f"/api/hr/reviews/{review['id']}/submit").status_code == 200
    assert client.post(f"/api/hr/reviews/{review['id']}/submit").status_code == 400

    # Submitted no longer editable.
    assert (
        client.put(f"/api/hr/reviews/{review['id']}", json={"rating": 3}).status_code
        == 400
    )

    r = client.post(
        f"/api/hr/reviews/{review['id']}/acknowledge",
        json={"employee_comment": "Read and discussed."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "acknowledged"
    assert body["employee_comment"] == "Read and discussed."
    assert body["rating"] == 5


def test_review_validation(client):
    emp = _create_employee(client)
    assert (
        client.post(
            "/api/hr/reviews",
            json={
                "employee_id": emp["id"],
                "period_start": "2026-06-30",
                "period_end": "2026-01-01",
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/hr/reviews",
            json={
                "employee_id": 999,
                "period_start": "2026-01-01",
                "period_end": "2026-06-30",
            },
        ).status_code
        == 404
    )
