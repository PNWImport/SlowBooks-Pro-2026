"""Analysis actions use real read-only queries and a stubbed provider boundary."""

from datetime import date

import pytest

from app.models.accounts import Account, AccountType
from app.services import ai_actions as actions
from tests import test_ai_query_tools as query_helpers

query_rows = query_helpers.query_rows


@pytest.mark.parametrize("key", list(actions.ACTIONS))
def test_analysis_action_data_and_provider_wiring(
    db_session, query_rows, monkeypatch, key
):
    calls = []

    def provider(*args, **kwargs):
        calls.append((args, kwargs))
        return "Synthetic analysis"

    monkeypatch.setattr(actions, "call_provider", provider)
    result = actions.run_action(
        key,
        db_session,
        date.today(),
        date.today(),
        "custom",
        "synthetic-model",
        "synthetic-secret",
        account_id="account",
        worker_url="https://worker.example.invalid",
        endpoint_url="https://provider.example.invalid",
    )
    assert result["analysis"] == "Synthetic analysis"
    assert result["action_key"] == key
    assert result["uses_period"] == actions.ACTIONS[key].uses_period
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:3] == ("custom", "synthetic-secret", "synthetic-model")
    assert args[3] == actions.SYSTEM_PROMPT
    assert "synthetic-secret" not in args[4]
    assert ("Period:" if result["uses_period"] else "As of:") in args[4]
    assert kwargs == {
        "account_id": "account",
        "worker_url": "https://worker.example.invalid",
        "endpoint_url": "https://provider.example.invalid",
    }
    if key == "unpaid_invoices":
        assert result["data"]["total_outstanding"] == 80
    elif key == "unpaid_bills":
        assert result["data"]["total_outstanding"] == 40
    elif key == "ar_aging":
        # 80 invoiced less 20 of unapplied payments (see test_ai_query_tools).
        assert result["data"]["total_outstanding"] == 60
    elif key == "ap_aging":
        assert result["data"]["total_outstanding"] == 20


def test_cash_position_excludes_non_cash_assets(db_session):
    db_session.add_all(
        [
            Account(name="Checking", account_type=AccountType.ASSET, balance=100),
            Account(name="Petty Cash", account_type=AccountType.ASSET, balance=20),
            Account(name="Equipment", account_type=AccountType.ASSET, balance=500),
        ]
    )
    db_session.commit()
    result = actions._run_cash_position(db_session, None, None)
    assert result["total_cash"] == 120
    assert [row["name"] for row in result["accounts"]] == ["Checking", "Petty Cash"]


def test_action_registry_groups_every_action_once():
    listed = actions.list_actions()
    assert len({group["category"] for group in listed}) == len(listed)
    keys = [row["key"] for group in listed for row in group["actions"]]
    assert keys == list(actions.ACTIONS)


def test_oversized_prompt_is_explicitly_truncated():
    prompt = actions._format_user_prompt(
        actions.ACTIONS["cash_position"], {"data": "x" * 20000}, None, None
    )
    assert "…(truncated)" in prompt
    assert len(prompt) < actions._MAX_DATA_CHARS + 500
    assert "As of:" in prompt


def test_unknown_action_does_not_contact_provider(db_session, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unknown action must not contact a provider")

    monkeypatch.setattr(actions, "call_provider", forbidden)
    with pytest.raises(ValueError, match="Unknown analysis action"):
        actions.run_action("unknown", db_session, None, None, "custom", "model", "key")


def test_provider_failure_is_not_presented_as_analysis(db_session, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr(actions, "call_provider", fail)
    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        actions.run_action(
            "cash_position", db_session, None, None, "custom", "model", "key"
        )
