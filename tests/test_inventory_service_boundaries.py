from decimal import Decimal

from app.models.accounts import Account, AccountType
from app.models.items import Item, ItemType, MovementType
from app.services import inventory_service as service


def _item(db_session, seed_accounts, *, tracked=True, quantity="0", cost="0"):
    item = Item(
        name="Boundary inventory item",
        item_type=ItemType.PRODUCT,
        track_inventory=tracked,
        quantity_on_hand=Decimal(quantity),
        avg_cost=Decimal(cost),
        asset_account_id=seed_accounts["1300"].id,
    )
    db_session.add(item)
    db_session.commit()
    return item


def test_nontracked_and_nonpositive_operations_are_noops(db_session, seed_accounts):
    plain = _item(db_session, seed_accounts, tracked=False)
    assert service.record_purchase(db_session, plain, 1, 1, "bill", 1) is None
    assert service.record_sale(db_session, plain, 1, "invoice", 1) is None
    assert service.record_adjustment(db_session, plain, 1) is None
    assert service.reverse_sale(db_session, plain, 1, "void", 1) is None

    tracked = _item(db_session, seed_accounts, quantity="1", cost="5")
    assert service.record_purchase(db_session, tracked, 0, 1, "bill", 1) is None
    assert service.record_sale(db_session, tracked, 0, "invoice", 1) is None
    assert service.record_adjustment(db_session, tracked, 0) is None
    assert service.reverse_sale(db_session, tracked, 0, "void", 1) is None


def test_inventory_zero_balance_resets_average_cost(db_session, seed_accounts):
    item = _item(db_session, seed_accounts, quantity="2", cost="7")
    movement = service._append_movement(
        db_session, item, MovementType.ADJUSTMENT, Decimal("-2"), Decimal("7")
    )
    assert movement.balance_qty == 0
    assert movement.balance_avg_cost == 0


def test_direct_purchase_posts_inventory_journal(db_session, seed_accounts):
    item = _item(db_session, seed_accounts)
    movement = service.record_purchase(
        db_session, item, 2, 3, "purchase_test", 42, post_journal=True
    )
    assert movement.transaction_id is not None
    assert movement.balance_qty == 2
    assert movement.balance_avg_cost == Decimal("3.0000")


def test_cogs_number_fallback_and_explicit_adjustment_cost(db_session, seed_accounts):
    for account in db_session.query(Account).filter_by(account_type=AccountType.COGS):
        account.account_type = AccountType.EXPENSE
    db_session.commit()
    assert service.get_cogs_account_id(db_session) == seed_accounts["5000"].id

    item = _item(db_session, seed_accounts, quantity="1", cost="5")
    movement = service.record_adjustment(
        db_session, item, 1, unit_cost=Decimal("9"), post_journal=False
    )
    assert movement.unit_cost == Decimal("9")


def test_reverse_sale_falls_back_to_current_average_cost(db_session, seed_accounts):
    item = _item(db_session, seed_accounts, quantity="1", cost="4")
    movement = service.reverse_sale(
        db_session,
        item,
        1,
        "void",
        99,
        original_source_type="invoice",
        original_source_id=999999,
    )
    assert movement.unit_cost == Decimal("4")
    assert movement.transaction_id is not None
