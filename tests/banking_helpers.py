"""Build ledger-backed fixtures for the pre-existing banking regressions."""

import itertools


_NUMBERS = itertools.count(1)


def _number(base):
    # The chart now refuses an account with no number; each fixture account
    # takes the next free one.
    return str(base + next(_NUMBERS))


def bank_account(client, name="Operating"):
    chart = client.post(
        "/api/accounts",
        json={
            "name": name,
            "account_number": _number(1100),
            "account_type": "asset",
            "bank_kind": "bank",
        },
    )
    assert chart.status_code == 201, chart.text
    response = client.post(
        "/api/banking/accounts",
        json={
            "name": name,
            "account_id": chart.json()["id"],
            "bank_name": "Test Bank",
            "last_four": "1234",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def bank_transaction(client, account_id, day, amount, **extra):
    category = client.post(
        "/api/accounts",
        json={
            "name": "Test category",
            "account_number": _number(6150),
            "account_type": "expense",
        },
    )
    assert category.status_code == 201, category.text
    response = client.post(
        "/api/banking/transactions",
        json={
            "bank_account_id": account_id,
            "date": day,
            "amount": amount,
            "category_account_id": category.json()["id"],
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    register = client.get(
        f"/api/banking/check-register?account_id={entry['account_id']}"
    ).json()
    entry["line_id"] = next(
        row["line_id"]
        for row in register["entries"]
        if row["transaction_id"] == entry["id"]
    )
    return entry
