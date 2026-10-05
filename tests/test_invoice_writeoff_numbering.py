"""Write-off credit-memo numbering handles collision paths deterministically."""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.credit_memos import CreditMemo
from app.routes.invoices import lifecycle
from tests.test_invoice_posting import _create_invoice


@pytest.mark.parametrize("mode", ["retry", "exhaust", "unrelated"])
def test_writeoff_memo_number_collision_handling(
    authed_client, db_session, seed_accounts, seed_customer, monkeypatch, mode
):
    invoice = _create_invoice(authed_client, seed_customer.id)
    real_flush = db_session.flush
    attempts = 0

    def flush(*args, **kwargs):
        nonlocal attempts
        if not any(isinstance(row, CreditMemo) for row in db_session.new):
            return real_flush(*args, **kwargs)
        attempts += 1
        should_raise = mode != "retry" or attempts == 1
        if should_raise:
            message = (
                "other constraint" if mode == "unrelated" else "memo_number unique"
            )
            raise IntegrityError("synthetic", {}, Exception(message))
        return real_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", flush)
    data = lifecycle.WriteOffRequest(date=date(2026, 9, 8))
    if mode == "retry":
        result = lifecycle.write_off_invoice(invoice["id"], data, db_session)
        assert result.is_write_off is True
        assert attempts >= 2
    elif mode == "unrelated":
        with pytest.raises(IntegrityError):
            lifecycle.write_off_invoice(invoice["id"], data, db_session)
    else:
        with pytest.raises(HTTPException) as caught:
            lifecycle.write_off_invoice(invoice["id"], data, db_session)
        assert caught.value.status_code == 503
        assert attempts == 10
