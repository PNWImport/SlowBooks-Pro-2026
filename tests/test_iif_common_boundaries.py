from app.models.accounts import Account, AccountType
from app.models.items import Item, ItemType
from app.services.iif_common import account_to_iif_type, item_to_iif_type


def test_account_to_iif_type_covers_number_ranges():
    cases = [
        (AccountType.ASSET, "1000", "BANK"),
        (AccountType.ASSET, "1100", "AR"),
        (AccountType.ASSET, "1200", "OCASSET"),
        (AccountType.ASSET, "1500", "FIXASSET"),
        (AccountType.ASSET, "2000", "OASSET"),
        (AccountType.LIABILITY, "2000", "AP"),
        (AccountType.LIABILITY, "2200", "OCLIAB"),
        (AccountType.LIABILITY, "2500", "LTLIAB"),
        (AccountType.EQUITY, None, "EQUITY"),
        (AccountType.INCOME, None, "INC"),
        (AccountType.EXPENSE, None, "EXP"),
        (AccountType.COGS, None, "COGS"),
    ]
    for account_type, number, expected in cases:
        assert (
            account_to_iif_type(
                Account(name="x", account_number=number, account_type=account_type)
            )
            == expected
        )


def test_item_to_iif_type_maps_all_item_kinds():
    expected = {
        ItemType.SERVICE: "SERV",
        ItemType.PRODUCT: "PART",
        ItemType.MATERIAL: "PART",
        ItemType.LABOR: "OTHC",
    }
    for item_type, iif_type in expected.items():
        assert item_to_iif_type(Item(name="x", item_type=item_type)) == iif_type
