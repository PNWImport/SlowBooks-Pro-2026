"""Structure smoke checks, not full PDF/UA conformance validation."""

import shutil
import subprocess

import pytest


def _assert_tagged(pdf, tmp_path):
    executable = shutil.which("pdfinfo")
    if not executable:
        pytest.skip("pdfinfo required for PDF structure inspection")
    path = tmp_path / "synthetic-report.pdf"
    path.write_bytes(pdf)
    result = subprocess.run(
        [executable, str(path)], capture_output=True, text=True, check=True
    )
    assert "Tagged:          yes" in result.stdout, result.stdout


def test_state_sui_pdf_is_tagged(db_session, tmp_path):
    from app.services.tax_forms.state_sui import generate_sui_pdf

    _assert_tagged(generate_sui_pdf(db_session, 2026, 1, None, {}), tmp_path)


def test_cobra_notice_pdf_is_tagged(client, tmp_path):
    employee = client.post(
        "/api/employees",
        json={"first_name": "Synthetic", "last_name": "Worker"},
    )
    assert employee.status_code == 201, employee.text
    plan = client.post(
        "/api/benefit-coverage/plans",
        json={"name": "Synthetic medical", "kind": "medical"},
    )
    assert plan.status_code == 201, plan.text
    enrollment = client.post(
        "/api/benefit-coverage/enrollments",
        json={
            "employee_id": employee.json()["id"],
            "plan_id": plan.json()["id"],
            "coverage_start": "2026-01-01",
        },
    )
    assert enrollment.status_code == 201, enrollment.text
    enrollment_id = enrollment.json()["id"]
    ended = client.post(
        f"/api/benefit-coverage/enrollments/{enrollment_id}/end",
        json={"coverage_end": "2026-06-30"},
    )
    assert ended.status_code == 200, ended.text
    response = client.post(
        f"/api/benefit-coverage/enrollments/{enrollment_id}/cobra-notice"
    )
    assert response.status_code == 200, response.text
    _assert_tagged(response.content, tmp_path)
