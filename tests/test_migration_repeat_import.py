"""The shared replay guard must be wired into every migration dialect."""

import pytest

from app.models.transactions import Transaction
from tests import test_migration_sources as sources
from tests import test_xero_import as xero
from tests import test_myob_import as myob


@pytest.mark.parametrize("length", [100, 101])
def test_import_reference_length_boundary(client, db_session, seed_accounts, length):
    ledger = sources.WAVE_GL.replace("T-1", "R" * length)

    def request(action):
        return client.post(
            f"/api/migration/wave/{action}",
            files=sources._files(
                **{"chart.csv": sources.WAVE_COA, "general_ledger.csv": ledger}
            ),
        ).json()

    before = db_session.query(Transaction).count()
    preview = request("dry-run")
    result = request("import")
    if length > 100:
        assert not preview["ok"]
        assert not result["ok"]
        assert any("100 characters" in error for error in preview["errors"])
        assert db_session.query(Transaction).count() == before
    else:
        assert preview["ok"] and result["ok"]
        assert result["imported_journals"] == 2
        assert request("import")["imported_journals"] == 0


@pytest.mark.parametrize(
    "source,coa,gl",
    [
        ("wave", sources.WAVE_COA, sources.WAVE_GL),
        ("sage", sources.SAGE_COA, sources.SAGE_GL),
        ("zoho", sources.ZOHO_COA, sources.ZOHO_GL),
        ("gnucash", sources.GNUCASH_COA, sources.GNUCASH_GL),
        ("xero", xero.COA_CSV, xero.GL_CSV),
        ("myob", myob.COA_TXT, myob.GL_TXT),
    ],
)
def test_repeat_import_preserves_journals_and_account_balances(
    client, db_session, seed_accounts, source, coa, gl
):
    from app.models.accounts import Account

    def request(action):
        response = client.post(
            f"/api/migration/{source}/{action}",
            files=sources._files(**{"chart.csv": coa, "general_ledger.csv": gl}),
        )
        assert response.status_code == 200, response.text
        assert response.json()["ok"], response.json()
        return response.json()

    first = request("import")
    assert first["imported_journals"] > 0
    before = {a.id: a.balance for a in db_session.query(Account).all()}
    count = db_session.query(Transaction).count()
    dry = request("dry-run")
    assert dry["duplicate_journals"] == first["imported_journals"]
    again = request("import")
    assert again["imported_journals"] == 0
    assert again["duplicate_journals"] == first["imported_journals"]
    db_session.expire_all()
    assert db_session.query(Transaction).count() == count
    assert {a.id: a.balance for a in db_session.query(Account).all()} == before


def test_repeat_import_does_not_repeat_synthesized_opening_balances(
    client, db_session, seed_accounts
):
    from app.models.accounts import Account

    bundle = {
        "chart.csv": xero.COA_CSV,
        "general_ledger.csv": xero.GL_CSV,
        # Balanced 100.00 residual represents the pre-export opening journal.
        "trial_balance.csv": xero.TB_CSV.replace("950.00", "1050.00").replace(
            "1150.00", "1250.00"
        ),
    }
    first = client.post("/api/migration/xero/import", files=sources._files(**bundle))
    assert first.status_code == 200 and first.json()["ok"], first.text
    assert (
        db_session.query(Transaction).filter_by(source_type="opening_balance").count()
        == 1
    )
    before = {a.id: a.balance for a in db_session.query(Account).all()}
    repeat = client.post("/api/migration/xero/import", files=sources._files(**bundle))
    assert repeat.status_code == 200 and repeat.json()["ok"], repeat.text
    assert repeat.json()["imported_journals"] == 0
    db_session.expire_all()
    assert (
        db_session.query(Transaction).filter_by(source_type="opening_balance").count()
        == 1
    )
    assert {a.id: a.balance for a in db_session.query(Account).all()} == before
