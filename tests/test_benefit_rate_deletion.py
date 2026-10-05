"""Deleting a dated benefit rate must reconnect the preceding interval only."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.benefits import BenefitCode
from app.services import benefits_engine


@pytest.mark.parametrize("remove", [0, 1, 2])
@pytest.mark.parametrize("bounded", [False, True])
def test_rate_deletion_preserves_contiguous_remaining_history(
    authed_client, db_session, remove, bounded
):
    from tests import test_benefits_engine as helpers

    code = helpers._code(
        authed_client, "SYN", rate={"effective_from": "2026-01-01", "employee_rate": 10}
    )
    url = f"/api/benefits/codes/{code['id']}/rates"
    for month, rate in [(2, 20), (3, 30)]:
        payload = {"effective_from": f"2026-{month:02d}-01", "employee_rate": rate}
        if month == 3 and bounded:
            payload["effective_to"] = "2026-03-31"
        result = authed_client.post(url, json=payload)
        assert result.status_code == 201, result.text
    rates = sorted(authed_client.get(url).json(), key=lambda row: row["effective_from"])
    assert authed_client.delete(f"{url}/{rates[remove]['id']}").status_code == 200
    remaining = sorted(
        authed_client.get(url).json(), key=lambda row: row["effective_from"]
    )
    expected = {
        0: [("2026-02-01", "2026-02-28"), ("2026-03-01", None)],
        1: [("2026-01-01", "2026-02-28"), ("2026-03-01", None)],
        2: [("2026-01-01", "2026-01-31"), ("2026-02-01", None)],
    }
    if bounded:
        start, _ = expected[remove][-1]
        expected[remove][-1] = (start, "2026-03-31")
    assert [
        (row["effective_from"], row["effective_to"]) for row in remaining
    ] == expected[remove]
    db_session.expire_all()
    stored = db_session.get(BenefitCode, code["id"])
    february = benefits_engine.resolve_rate(stored, date(2026, 2, 15))
    assert february.employee_rate == Decimal("10" if remove == 1 else "20")
    assert authed_client.delete(f"{url}/999999").status_code == 404


def test_rate_deletion_preserves_intentional_gap(authed_client, db_session):
    from tests import test_benefits_engine as helpers

    code = helpers._code(
        authed_client,
        "GAP",
        rate={
            "effective_from": "2026-01-01",
            "effective_to": "2026-01-15",
            "employee_rate": 10,
        },
    )
    url = f"/api/benefits/codes/{code['id']}/rates"
    response = authed_client.post(
        url, json={"effective_from": "2026-02-01", "employee_rate": 20}
    )
    assert response.status_code == 201, response.text
    assert authed_client.delete(f"{url}/{response.json()['id']}").status_code == 200
    remaining = authed_client.get(url).json()
    assert len(remaining) == 1
    assert remaining[0]["effective_to"] == "2026-01-15"
    db_session.expire_all()
    assert (
        benefits_engine.resolve_rate(
            db_session.get(BenefitCode, code["id"]), date(2026, 2, 15)
        )
        is None
    )
