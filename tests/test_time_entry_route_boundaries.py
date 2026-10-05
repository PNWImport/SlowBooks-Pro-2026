"""Time-entry filters, locks, transitions, and job-posting contracts."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.payroll import PayRun
from app.models.time_entries import TimeEntry
from app.routes import time_entries
from app.services import job_costing
from app.services import closing_date
from app.services.safe_errors import DataProblem, GENERIC


def _employee(client):
    response = client.post(
        "/api/employees", json={"first_name": "Time", "last_name": "Worker"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _entry(client, employee_id, day="2026-09-08", hours=8):
    response = client.post(
        "/api/time-entries",
        json={"employee_id": employee_id, "date": day, "hours_regular": hours},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_time_entry_filters_update_delete_and_missing(client):
    employee_id = _employee(client)
    entry = _entry(client, employee_id)
    _entry(client, employee_id, "2026-09-09", 4)
    filtered = client.get(
        f"/api/time-entries?employee_id={employee_id}&start=2026-09-08&end=2026-09-08&status=draft"
    )
    assert filtered.status_code == 200
    assert [row["id"] for row in filtered.json()] == [entry["id"]]
    assert client.get("/api/time-entries?status=invalid").status_code == 400
    assert (
        client.post(
            "/api/time-entries",
            json={"employee_id": 999999, "date": "2026-09-08", "hours_regular": 8},
        ).status_code
        == 404
    )

    endpoint = f"/api/time-entries/{entry['id']}"
    changed = client.put(endpoint, json={"hours_regular": 6, "notes": "changed"})
    assert changed.status_code == 200
    assert changed.json()["hours_regular"] == 6
    assert (
        client.put("/api/time-entries/999999", json={"hours_regular": 1}).status_code
        == 404
    )
    assert client.delete("/api/time-entries/999999").status_code == 404
    assert client.delete(endpoint).status_code == 200


def test_time_entry_pay_run_locks(client, db_session):
    employee_id = _employee(client)
    entry = _entry(client, employee_id)
    pay_run = PayRun(
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 8),
        pay_date=date(2026, 9, 10),
    )
    db_session.add(pay_run)
    db_session.flush()
    row = db_session.query(TimeEntry).filter(TimeEntry.id == entry["id"]).first()
    row.pay_run_id = pay_run.id
    db_session.commit()
    endpoint = f"/api/time-entries/{entry['id']}"

    assert client.put(endpoint, json={"hours_regular": 2}).status_code == 400
    assert client.delete(endpoint).status_code == 400
    assert client.post(f"{endpoint}/submit").status_code == 400
    assert (
        client.post(f"{endpoint}/approve", json={"approved_by": "A"}).status_code == 400
    )
    assert client.post(f"{endpoint}/reject").status_code == 400


@pytest.mark.parametrize("error_type", [DataProblem, ValueError])
def test_time_entry_transition_and_posting_edges(client, monkeypatch, error_type):
    employee_id = _employee(client)
    approved = _entry(client, employee_id)
    approved_url = f"/api/time-entries/{approved['id']}"
    assert (
        client.post(f"{approved_url}/approve", json={"approved_by": "A"}).status_code
        == 200
    )
    assert client.put(approved_url, json={"hours_regular": 1}).status_code == 400
    assert client.delete(approved_url).status_code == 400
    assert (
        client.post(f"{approved_url}/approve", json={"approved_by": "A"}).status_code
        == 400
    )

    assert client.post("/api/time-entries/999999/submit").status_code == 404
    assert client.post("/api/time-entries/999999/approve", json={}).status_code == 404
    assert client.post("/api/time-entries/999999/reject").status_code == 404
    assert client.post("/api/time-entries/999999/post-to-job").status_code == 404

    rejected = _entry(client, employee_id, "2026-09-10")
    rejected_url = f"/api/time-entries/{rejected['id']}"
    assert client.post(f"{rejected_url}/reject").status_code == 200
    assert client.post(f"{rejected_url}/reject").status_code == 400

    fake_cost = SimpleNamespace(id=7, number="JC-7", total=12.5)
    monkeypatch.setattr(
        job_costing, "post_time_entry_to_job", lambda db, row: fake_cost
    )
    single = client.post(f"{approved_url}/post-to-job")
    assert single.status_code == 200
    assert single.json()["job_cost_id"] == 7
    batch = client.post(
        "/api/time-entries/post-to-job", json={"ids": [approved["id"], 999999]}
    )
    assert batch.status_code == 200
    assert batch.json()["posted"] == 1
    assert batch.json()["results"][1]["error"] == "not found"

    def reject_post(db, row):
        raise error_type("not postable")

    monkeypatch.setattr(job_costing, "post_time_entry_to_job", reject_post)
    failed_single = client.post(f"{approved_url}/post-to-job")
    assert failed_single.status_code == 400
    expected = "not postable" if error_type is DataProblem else GENERIC
    assert failed_single.json()["detail"] == expected
    failed_batch = client.post(
        "/api/time-entries/post-to-job", json={"ids": [approved["id"]]}
    )
    assert failed_batch.json()["posted"] == 0
    assert failed_batch.json()["results"][0]["error"] == expected


def test_time_entry_classification(client):
    response = client.post(
        "/api/time-entries/classify",
        json={"weeks": [[8, 8, 8, 8, 8, 4]], "state": "WA"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["overtime"] == 4


@pytest.mark.parametrize("error_type", [DataProblem, ValueError])
def test_reject_translates_job_cost_void_failure(monkeypatch, error_type):
    entry = SimpleNamespace(
        id=1,
        pay_run_id=None,
        status="submitted",
        job_cost_id=7,
    )
    job_cost = SimpleNamespace(date=date(2026, 9, 8), status="posted")

    class FakeDB:
        def query(self, *args):
            return self

        def filter(self, *args):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return entry

        def get(self, *args):
            return job_cost

    monkeypatch.setattr(closing_date, "check_closing_date", lambda db, day: None)
    monkeypatch.setattr(
        job_costing,
        "void_job_cost",
        lambda db, row: (_ for _ in ()).throw(error_type("cannot void")),
    )
    with pytest.raises(HTTPException) as exc:
        time_entries.reject_time_entry(1, FakeDB())
    assert exc.value.detail == ("cannot void" if error_type is DataProblem else GENERIC)
    assert exc.value.status_code == 400
