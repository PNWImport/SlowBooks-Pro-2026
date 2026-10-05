"""Boundary contracts for payroll PDF and ACH exports."""

from datetime import date

from app.models.payroll import Employee, PayRun, PayRunStatus, PayStub


def _run_with_stub(db_session, *, status=PayRunStatus.DRAFT):
    employee = Employee(first_name="Export", last_name="Worker")
    run = PayRun(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 15),
        pay_date=date(2026, 1, 20),
        status=status,
    )
    db_session.add_all([employee, run])
    db_session.flush()
    stub = PayStub(
        pay_run_id=run.id, employee_id=employee.id, gross_pay=100, net_pay=80
    )
    db_session.add(stub)
    db_session.commit()
    return run, stub, employee


def _originating(**overrides):
    body = {
        "immediate_destination": "021000021",
        "immediate_origin": "1234567890",
        "originating_dfi_id": "02100002",
    }
    body.update(overrides)
    return body


def test_paystub_export_not_found_and_success_context(client, db_session, monkeypatch):
    missing = client.get("/api/payroll/987/paystub/654")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Pay stub not found"

    run, stub, employee = _run_with_stub(db_session)
    captured = {}

    def generate(pdf_stub, pdf_employee, pdf_run, company, ytd, ytd_stubs=None):
        captured.update(
            stub=pdf_stub,
            employee=pdf_employee,
            run=pdf_run,
            company=company,
            ytd=ytd,
        )
        return b"synthetic-pdf"

    monkeypatch.setattr(
        "app.routes.payroll.exports.employee_ytd", lambda *_: {"gross": 100}
    )
    monkeypatch.setattr("app.services.paystub_pdf.generate_paystub_pdf", generate)

    response = client.get(f"/api/payroll/{run.id}/paystub/{stub.id}")

    assert response.status_code == 200
    assert response.content == b"synthetic-pdf"
    assert response.headers["content-type"] == "application/pdf"
    # Named for the person and the pay date, not internal ids
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('inline; filename="Pay-Stub_')
    assert "Export-Worker" in disposition
    assert captured["stub"].id == stub.id
    assert captured["employee"].id == employee.id
    assert captured["run"].id == run.id
    assert captured["ytd"] == {"gross": "100.00", "net": "80.00"}
    assert {"name", "address", "phone", "ein"} <= set(captured["company"])


def test_nacha_export_rejects_unknown_and_unprocessed_runs(client, db_session):
    unknown = client.post("/api/payroll/987/nacha", json=_originating())
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Pay run not found"

    run, _, _ = _run_with_stub(db_session)
    unprocessed = client.post(f"/api/payroll/{run.id}/nacha", json=_originating())
    assert unprocessed.status_code == 400
    assert unprocessed.json()["detail"] == "Pay run must be processed before ACH export"


def test_nacha_export_supplies_company_defaults_and_translates_errors(
    client, db_session, monkeypatch
):
    run, _, _ = _run_with_stub(db_session, status=PayRunStatus.PROCESSED)
    calls = []

    def generate(_db, run_id, originating):
        calls.append((run_id, originating))
        if len(calls) == 1:
            raise ValueError("No direct-deposit accounts")
        return "101 synthetic ACH\n"

    monkeypatch.setattr("app.services.nacha_export.generate_nacha_file", generate)

    # Without saved company ACH details the export refuses before the
    # generator runs: the file carries full account numbers, so the
    # company's own origination details must exist first.
    rejected = client.post(f"/api/payroll/{run.id}/nacha", json=_originating())
    assert rejected.status_code == 400
    assert "ACH details" in rejected.json()["detail"]
    assert calls == []

    from app.services import ach_settings

    ach_settings.save(
        db_session,
        {
            "immediate_destination": "021000021",
            "immediate_origin": "123456789",
            "originating_dfi_id": "02100002",
            "company_account": "987654321",
        },
    )
    db_session.commit()

    first = client.post(f"/api/payroll/{run.id}/nacha", json=_originating())
    assert first.status_code == 400  # the stub's first call raises
    assert first.json()["detail"] == "No direct-deposit accounts"
    assert calls[0][0] == run.id
    assert calls[0][1]["effective_date"] == run.pay_date
    assert "company_name" in calls[0][1] and "company_id" in calls[0][1]
    # The saved details filled the origination fields the body left empty.
    assert calls[0][1]["immediate_destination"] == "021000021"

    accepted = client.post(
        f"/api/payroll/{run.id}/nacha",
        json=_originating(
            effective_date="2026-02-01",
            company_name="Acme Payroll",
            company_id="12-3456789",
        ),
    )
    assert accepted.status_code == 200
    assert accepted.text == "101 synthetic ACH\n"
    assert accepted.headers["content-type"].startswith("text/plain")
    assert accepted.headers["content-disposition"] == (
        f"attachment; filename=payroll_{run.id}.ach"
    )
    assert calls[1][1]["effective_date"] == date(2026, 2, 1)
    assert calls[1][1]["company_name"] == "Acme Payroll"
    assert calls[1][1]["company_id"] == "12-3456789"
