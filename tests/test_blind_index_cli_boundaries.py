"""Blind-index recovery and CLI boundaries without touching a live database."""

import runpy
import sys

import pytest

from app.services import blind_index as index


def test_reindex_reports_unregistered_model_and_unknown_lookup(monkeypatch):
    monkeypatch.setattr(index, "_REGISTERED", {("gone_table", "secret"): "secret_bidx"})
    assert index.reindex_all(db=None) == {
        "checked": 0,
        "rewritten": 0,
        "unchanged": 0,
        "failed": 1,
    }
    assert index._model_for_table("not-a-real-table") is None


def test_cli_rejects_no_command(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["blind_index"])
    with pytest.raises(SystemExit) as exited:
        index._cli()
    assert exited.value.code == 2
    assert "reindex" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("result", "expected_exit"),
    [
        ({"checked": 2, "unchanged": 1, "rewritten": 1, "failed": 0}, 0),
        ({"checked": 2, "unchanged": 0, "rewritten": 0, "failed": 1}, 1),
    ],
)
def test_cli_runs_canonical_reindex_and_closes_session(
    monkeypatch, capsys, result, expected_exit
):
    import app.database as database

    closed = []

    class Session:
        def close(self):
            closed.append(True)

    seen = []
    monkeypatch.setattr(database, "SessionLocal", Session)
    monkeypatch.setattr(
        index,
        "reindex_all",
        lambda db, dry_run: seen.append((db, dry_run)) or result,
    )
    monkeypatch.setattr(sys, "argv", ["blind_index", "reindex", "--dry-run"])

    with pytest.raises(SystemExit) as exited:
        index._cli()
    assert exited.value.code == expected_exit
    assert isinstance(seen[0][0], Session) and seen[0][1] is True
    assert closed == [True]
    output = capsys.readouterr().out
    assert "checked" in output and "dry-run" in output


# The module is already imported (and monkeypatched) when runpy re-runs it as
# __main__ — the exact situation runpy warns about, and the point of the test.
@pytest.mark.filterwarnings(
    "ignore:.*found in sys.modules after import of package:RuntimeWarning"
)
def test_main_module_delegates_to_canonical_cli(monkeypatch):
    called = []
    monkeypatch.setattr(index, "_cli", lambda: called.append(True))
    runpy.run_module("app.services.blind_index", run_name="__main__")
    assert called == [True]
