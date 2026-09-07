# ============================================================================
# The Benefits page's contract with its backend.
# ----------------------------------------------------------------------------
# app/static/js/benefit_coverage.js renders plans, enrollments, dependents and the ACA
# 1095/1094 derivation. tests/test_wiring.py proves the paths resolve; these
# tests pin the RESPONSE SHAPES and the two server rules the page mirrors in
# its UI, which wiring cannot see.
#
# The UI mirrors two server rules, and a drift in either is silent:
#   * COBRA needs a MEDICAL plan and an ended enrollment. The page only offers
#     the button then; if the server rule moved, the button would either be
#     missing where it should work or produce a 400 the operator has to read.
#   * An employee may hold only one OPEN enrollment per plan. That guard is
#     `coverage_end IS NULL` on an encrypted column — it works because NULL
#     survives encryption, and it is worth a test saying so.
#
# Driven end-to-end in Chromium before shipping: plan create, enroll,
# duplicate refusal, dependent add, ACA all-12-months, end coverage, ACA
# narrowing to Jan-Jul, and the COBRA blob download.
# ============================================================================

from pathlib import Path

import pytest

JS = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "static"
    / "js"
    / "benefit_coverage.js"
)


def _employee(client, first="Bea"):
    r = client.post(
        "/api/employees",
        json={
            "first_name": first,
            "last_name": "Covered",
            "pay_type": "salary",
            "pay_rate": 60000,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "WA",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _plan(client, **over):
    body = {
        "name": "Gold PPO",
        "kind": "medical",
        "carrier_name": "Blue Shield of Testland",
        "monthly_premium_employee": 150,
        "monthly_premium_employer": 450,
    }
    body.update(over)
    r = client.post("/api/benefit-coverage/plans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _enroll(client, emp_id, plan_id, start="2026-01-01"):
    r = client.post(
        "/api/benefit-coverage/enrollments",
        json={"employee_id": emp_id, "plan_id": plan_id, "coverage_start": start},
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- registration -----------------------------------------------------------


def test_the_page_is_wired_into_the_router_and_nav():
    root = JS.parents[3]
    app_js = (root / "app" / "static" / "js" / "app.js").read_text()
    index = (root / "index.html").read_text()

    assert "'/hr/benefits'" in app_js
    assert "BenefitCoveragePage.render()" in app_js
    assert 'href="#/hr/benefits"' in index
    assert "/static/js/benefit_coverage.js" in index


def test_the_page_navigates_to_a_route_that_exists():
    """A refresh-by-navigate to the wrong hash renders an empty page and
    nothing raises — this exact typo shipped and was caught in a browser."""
    import re

    app_js = (JS.parents[3] / "app" / "static" / "js" / "app.js").read_text()
    routes = set(re.findall(r"^\s*'(/[^']*)':\s*\{", app_js, re.M))
    for target in re.findall(r"App\.navigate\('#(/[^']*)'\)", JS.read_text()):
        assert (
            target in routes
        ), f"benefit_coverage.js navigates to unregistered {target!r}"


# --- response shapes the page renders ---------------------------------------


def test_plan_response_carries_every_column_the_table_shows(client):
    plan = _plan(client, self_insured=True)
    for key in (
        "id",
        "name",
        "kind",
        "carrier_name",
        "provides_mec",
        "self_insured",
        "monthly_premium_employee",
        "monthly_premium_employer",
        "is_active",
    ):
        assert key in plan, f"plan response lost {key}, which the table renders"


def test_enrollment_response_carries_plan_kind(client):
    """The page needs the kind to decide whether COBRA applies. Without it the
    client would have to join plans itself — a client re-deriving a server
    rule, which is how the two drift apart."""
    emp = _employee(client)
    plan = _plan(client)
    row = _enroll(client, emp["id"], plan["id"])
    assert row["plan_kind"] == "medical"
    for key in (
        "id",
        "employee_id",
        "employee_name",
        "plan_name",
        "coverage_start",
        "coverage_end",
        "status",
        "dependents",
    ):
        assert key in row


def test_enrollment_list_includes_dependents_inline(client):
    emp = _employee(client)
    plan = _plan(client)
    enr = _enroll(client, emp["id"], plan["id"])
    client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/dependents",
        json={"name": "Kid Covered", "relationship_kind": "child"},
    )
    row = client.get("/api/benefit-coverage/enrollments").json()[0]
    assert row["dependents"][0]["name"] == "Kid Covered"
    assert row["dependents"][0]["relationship_kind"] == "child"


def test_aca_response_carries_the_month_grid_and_the_caveat(client, seed_accounts):
    emp = _employee(client)
    plan = _plan(client, self_insured=True)
    _enroll(client, emp["id"], plan["id"])

    data = client.get("/api/tax-forms/1095?year=2026").json()
    for key in ("form_count", "monthly_covered_employee_counts", "forms", "note"):
        assert key in data
    # The page prints `note` verbatim. It is the "not modelled / verify before
    # filing" caveat, and dropping it would make the grid look authoritative.
    assert data["note"], "the ACA caveat must not be empty — the page renders it"
    # JSON object keys are strings on the wire; JS coerces on lookup.
    counts = data["monthly_covered_employee_counts"]
    assert {str(k) for k in counts} == {str(m) for m in range(1, 13)}

    form = data["forms"][0]
    for key in (
        "name",
        "ssn_last_four",
        "months_covered",
        "all_12_months",
        "plans",
        "self_insured",
        "covered_individuals",
    ):
        assert key in form


# --- the two server rules the UI mirrors ------------------------------------


def test_cobra_needs_an_ended_medical_enrollment(client, seed_accounts):
    """The page shows the COBRA button only for `coverage_end` set AND
    `plan_kind == 'medical'`. Both halves of that rule live on the server."""
    emp = _employee(client)
    medical = _plan(client)
    enr = _enroll(client, emp["id"], medical["id"])

    # Still open -> refused.
    r = client.post(f"/api/benefit-coverage/enrollments/{enr['id']}/cobra-notice")
    assert r.status_code == 400
    assert "end it first" in r.json()["detail"]

    # Ended -> works.
    client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-07-15"},
    )
    assert (
        client.post(
            f"/api/benefit-coverage/enrollments/{enr['id']}/cobra-notice"
        ).status_code
        == 200
    )


def test_cobra_is_refused_for_a_non_medical_plan(client, seed_accounts):
    emp = _employee(client)
    vision = _plan(client, name="Eyes", kind="vision")
    enr = _enroll(client, emp["id"], vision["id"])
    client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-07-15"},
    )
    r = client.post(f"/api/benefit-coverage/enrollments/{enr['id']}/cobra-notice")
    assert r.status_code == 400
    assert "medical" in r.json()["detail"]


def test_one_open_enrollment_per_plan(client):
    """The duplicate guard is `coverage_end IS NULL` on an ENCRYPTED column.
    It works because NULL survives encryption — see app/models/benefits.py."""
    emp = _employee(client)
    plan = _plan(client)
    _enroll(client, emp["id"], plan["id"])

    dup = client.post(
        "/api/benefit-coverage/enrollments",
        json={
            "employee_id": emp["id"],
            "plan_id": plan["id"],
            "coverage_start": "2026-06-01",
        },
    )
    assert dup.status_code == 400
    assert "already has an open enrollment" in dup.json()["detail"]

    # Ending it frees the slot, proving the NULL check reads the real column
    # rather than always matching.
    enrollments = client.get("/api/benefit-coverage/enrollments").json()
    client.post(
        f"/api/benefit-coverage/enrollments/{enrollments[0]['id']}/end",
        json={"coverage_end": "2026-05-31"},
    )
    again = client.post(
        "/api/benefit-coverage/enrollments",
        json={
            "employee_id": emp["id"],
            "plan_id": plan["id"],
            "coverage_start": "2026-06-01",
        },
    )
    assert again.status_code == 201, again.text


def test_aca_months_narrow_when_coverage_ends_mid_year(client, seed_accounts):
    """Any day of the month counts, so a July 15 end still covers July. The
    page renders this as the month grid; getting it wrong misstates a filing."""
    emp = _employee(client)
    plan = _plan(client)
    enr = _enroll(client, emp["id"], plan["id"], start="2026-01-01")
    client.post(
        f"/api/benefit-coverage/enrollments/{enr['id']}/end",
        json={"coverage_end": "2026-07-15"},
    )
    data = client.get("/api/tax-forms/1095?year=2026").json()
    assert data["forms"][0]["months_covered"] == [1, 2, 3, 4, 5, 6, 7]
    assert data["forms"][0]["all_12_months"] is False
    counts = data["monthly_covered_employee_counts"]
    assert counts[8 if 8 in counts else "8"] == 0
    assert counts[7 if 7 in counts else "7"] == 1


# --- honesty ----------------------------------------------------------------


def test_the_page_prints_the_aca_caveat():
    """`data.note` says offer codes and safe harbors are not modelled. A grid
    of green ticks with no caveat reads as a filing-ready return."""
    assert "data.note" in JS.read_text()


def test_the_page_says_what_is_encrypted_when_collecting_a_dependent():
    """A dependent is a family member who never consented to this system
    directly. The form says what happens to their identifiers."""
    source = JS.read_text()
    assert "encrypted at rest" in source


@pytest.mark.parametrize(
    "kind", ["medical", "dental", "vision", "life", "disability", "other"]
)
def test_every_plan_kind_is_offerable_from_the_page(client, kind):
    """A kind missing from the dropdown is a kind the operator cannot record."""
    assert f'"{kind}"' in JS.read_text() or f"'{kind}'" in JS.read_text()
    assert _plan(client, name=f"Plan {kind}", kind=kind)["kind"] == kind
