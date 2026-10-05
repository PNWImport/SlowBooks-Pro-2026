"""OFX parser fallback/native shapes and import idempotency."""

import sys
import types
from datetime import date, datetime
from decimal import Decimal

from app.models.banking import BankAccount, BankTransaction
from app.services import ofx_import as ofx


def test_parse_ofx_fallback_and_tag_extraction(monkeypatch):
    monkeypatch.setitem(sys.modules, "ofxparse", None)
    rows = ofx.parse_ofx("""
        <STMTTRN><FITID> abc </FITID><DTPOSTED>20260908</DTPOSTED>
        <TRNAMT>-12.34</TRNAMT><NAME> Corner Shop </NAME><MEMO> lunch </MEMO></STMTTRN>
        <STMTTRN><FITID>missing-amount</FITID><DTPOSTED>20260909</DTPOSTED></STMTTRN>
        """)

    assert rows == [
        {
            "fitid": "abc",
            "date": date(2026, 9, 8),
            "amount": Decimal("-12.34"),
            "payee": "Corner Shop",
            "memo": "lunch",
            "type": "",
        }
    ]
    assert ofx._extract_tag("<NAME>  Trim me  ", "NAME") == "Trim me"
    assert ofx._extract_tag("<OTHER>x", "NAME") == ""


def test_parse_ofx_uses_available_native_parser(monkeypatch):
    transaction = types.SimpleNamespace(
        id="native-id",
        date=datetime(2026, 9, 8, 13, 0),
        amount="3.50",
        payee=None,
        memo="fallback memo",
        type=None,
    )
    date_only_transaction = types.SimpleNamespace(
        id="date-only-id",
        date=date(2026, 9, 9),
        amount=1,
        payee="Payee",
        memo=None,
        type="DEBIT",
    )
    account = types.SimpleNamespace(
        statement=types.SimpleNamespace(
            transactions=[transaction, date_only_transaction]
        )
    )

    class Parser:
        @staticmethod
        def parse(stream):
            assert stream.read() == b"native input"
            return types.SimpleNamespace(accounts=[account])

    fake_module = types.ModuleType("ofxparse")
    fake_module.OfxParser = Parser
    monkeypatch.setitem(sys.modules, "ofxparse", fake_module)

    assert ofx.parse_ofx("native input") == [
        {
            "fitid": "native-id",
            "date": date(2026, 9, 8),
            "amount": Decimal("3.50"),
            "payee": "fallback memo",
            "memo": "fallback memo",
            "type": "",
        },
        {
            "fitid": "date-only-id",
            "date": date(2026, 9, 9),
            "amount": Decimal("1"),
            "payee": "Payee",
            "memo": "",
            "type": "DEBIT",
        },
    ]
    assert [row["fitid"] for row in ofx.parse_ofx(b"native input")] == [
        "native-id",
        "date-only-id",
    ]


def test_import_transactions_deduplicates_and_only_runs_rules_when_needed(
    db_session, monkeypatch
):
    account = BankAccount(name="OFX test")
    db_session.add(account)
    db_session.flush()
    db_session.add(
        BankTransaction(
            bank_account_id=account.id,
            date=date(2026, 1, 1),
            amount=Decimal("1"),
            import_id="known",
        )
    )
    db_session.commit()
    calls = []
    monkeypatch.setattr(
        ofx, "apply_bank_rules", lambda db, bank_id: calls.append(bank_id)
    )

    first = ofx.import_transactions(
        db_session,
        account.id,
        [
            {"fitid": "known", "date": date(2026, 1, 2), "amount": Decimal("9")},
            {"fitid": "", "date": date(2026, 1, 3), "amount": Decimal("2")},
            {
                "fitid": "new",
                "date": date(2026, 1, 4),
                "amount": Decimal("-3"),
                "payee": "Vendor",
                "memo": "invoice",
            },
        ],
        import_source="simplefin",
    )
    assert first == {"imported": 2, "skipped": 1, "matched": 0, "total": 3}
    assert calls == [account.id]
    inserted = (
        db_session.query(BankTransaction)
        .filter(BankTransaction.import_id == "new")
        .one()
    )
    assert (inserted.payee, inserted.description, inserted.import_source) == (
        "Vendor",
        "invoice",
        "simplefin",
    )
    assert inserted.match_status == "unmatched"

    second = ofx.import_transactions(
        db_session,
        account.id,
        [{"fitid": "new", "date": date(2026, 1, 4), "amount": Decimal("-3")}],
    )
    assert second == {"imported": 0, "skipped": 1, "matched": 0, "total": 1}
    assert calls == [account.id]
