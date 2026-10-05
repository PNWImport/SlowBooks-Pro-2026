"""Group replacements reject ambiguous repeated benefit codes atomically."""

import pytest

from tests.test_benefits_engine import _code, _emp


@pytest.mark.parametrize("replace", [False, True])
def test_duplicate_group_codes_rejected(authed_client, replace):
    code = _code(authed_client, "DUP")
    codes = [
        {"benefit_code_id": code["id"], "employee_rate": 10},
        {"benefit_code_id": code["id"], "employee_rate": 20},
    ]
    url = "/api/benefits/groups"
    if replace:
        created = authed_client.post(
            url, json={"name": "Synthetic group", "codes": codes[:1]}
        )
        assert created.status_code == 201, created.text
        response = authed_client.put(f"{url}/{created.json()['id']}/codes", json=codes)
    else:
        response = authed_client.post(
            url, json={"name": "Synthetic group", "codes": codes}
        )
    assert response.status_code == 409, response.text
    groups = authed_client.get(url).json()
    if replace:
        assert len(groups) == 1
        assert len(groups[0]["codes"]) == 1
        assert groups[0]["codes"][0]["employee_rate"] == 10
    else:
        assert groups == []


def test_group_replacement_and_deletion_contract(authed_client):
    first = _code(authed_client, "FIRST")
    second = _code(authed_client, "SECOND")
    employee = _emp(authed_client)
    url = "/api/benefits/groups"
    created = authed_client.post(
        url,
        json={"name": "Synthetic", "codes": [{"benefit_code_id": first["id"]}]},
    )
    assert created.status_code == 201, created.text
    group_url = f"{url}/{created.json()['id']}"
    assert authed_client.post(url, json={"name": "Synthetic"}).status_code == 409
    updated = authed_client.put(group_url, json={"description": "Updated"})
    assert updated.status_code == 200
    assert updated.json()["description"] == "Updated"
    changed = authed_client.put(
        f"{group_url}/codes", json=[{"benefit_code_id": second["id"]}]
    )
    assert changed.status_code == 200, changed.text
    assert [row["code"] for row in changed.json()["codes"]] == ["SECOND"]
    invalid = authed_client.put(
        f"{group_url}/codes", json=[{"benefit_code_id": 999999}]
    )
    assert invalid.status_code == 404
    assert authed_client.get(url).json()[0]["codes"][0]["code"] == "SECOND"
    members = authed_client.put(
        f"{group_url}/members", json={"employee_ids": [employee["id"]]}
    )
    assert members.status_code == 200
    assert members.json()["member_count"] == 1
    invalid = authed_client.put(f"{group_url}/members", json={"employee_ids": [999999]})
    assert invalid.status_code == 404
    assert authed_client.get(url).json()[0]["member_count"] == 1
    assert authed_client.delete(group_url).status_code == 200
    assert authed_client.get(url).json() == []
    assert (
        authed_client.get(f"/api/employees/{employee['id']}").json()[
            "employee_group_id"
        ]
        is None
    )
    assert authed_client.delete(group_url).status_code == 404
