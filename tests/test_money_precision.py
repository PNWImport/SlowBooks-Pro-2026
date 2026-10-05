"""Posted currency is cents; rates and quantities use their own precision."""

import pytest
from pydantic import ValidationError

from app.models.items import ItemType
from app.routes.fixed_assets import AssetCreate
from app.routes.invoices.lifecycle import WriteOffRequest
from app.schemas.banking import BankTransactionCreate
from app.schemas.banking import ReconciliationCreate
from app.schemas.bills import BillLineCreate
from app.schemas.budgets import BudgetCreate
from app.schemas.cc_charges import CCChargeCreate
from app.schemas.deposits import DepositCreate
from app.schemas.expenses import ExpenseCreate
from app.schemas.in_kind import InKindLineCreate
from app.schemas.invoices import InvoiceLineCreate
from app.schemas.items import ItemCreate
from app.schemas.jobs import JobCreate
from app.schemas.journal import JournalLineCreate
from app.schemas.job_costing import AllocationCreate, EquipmentCreate, JobBudgetRow
from app.schemas.sales_receipts import SalesReceiptCreate
from app.schemas.transfers import TransferCreate

CASES = [
    (
        BankTransactionCreate,
        {
            "account_id": 1,
            "date": "2026-01-01",
            "amount": "VALUE",
            "category_account_id": 2,
        },
    ),
    (CCChargeCreate, {"date": "2026-01-01", "account_id": 1, "amount": "VALUE"}),
    (
        DepositCreate,
        {"deposit_to_account_id": 1, "date": "2026-01-01", "total": "VALUE"},
    ),
    (
        ExpenseCreate,
        {
            "date": "2026-01-01",
            "expense_account_id": 1,
            "paid_from_account_id": 2,
            "amount": "VALUE",
        },
    ),
    (
        TransferCreate,
        {
            "date": "2026-01-01",
            "from_account_id": 1,
            "to_account_id": 2,
            "amount": "VALUE",
        },
    ),
    (InvoiceLineCreate, {"quantity": 1, "rate": "VALUE"}),
    (BillLineCreate, {"quantity": 1, "rate": "VALUE"}),
    (JournalLineCreate, {"account_id": 1, "debit": "VALUE"}),
    (BudgetCreate, {"account_id": 1, "year": 2026, "month": 1, "amount": "VALUE"}),
    (ItemCreate, {"name": "Widget", "item_type": ItemType.PRODUCT, "rate": "VALUE"}),
    (JobCreate, {"customer_id": 1, "name": "Job", "contract_amount": "VALUE"}),
    (
        InKindLineCreate,
        {"description": "Gift", "fair_value": "VALUE", "debit_account_id": 1},
    ),
    (
        AssetCreate,
        {
            "name": "Asset",
            "purchase_date": "2026-01-01",
            "purchase_price": "VALUE",
            "asset_type_id": 1,
        },
    ),
    (
        SalesReceiptCreate,
        {
            "customer_id": 1,
            "date": "2026-01-01",
            "fair_value_amount": "VALUE",
            "lines": [{"description": "Donation", "quantity": 1, "rate": "1.00"}],
        },
    ),
    (WriteOffRequest, {"date": "2026-01-01", "amount": "VALUE"}),
    (EquipmentCreate, {"name": "Loader", "hourly_rate": "VALUE"}),
    (AllocationCreate, {"date": "2026-01-01", "amount": "VALUE"}),
    (JobBudgetRow, {"amount": "VALUE"}),
    (
        ReconciliationCreate,
        {"account_id": 1, "statement_date": "2026-01-01", "statement_balance": "VALUE"},
    ),
]


@pytest.mark.parametrize("schema,payload", CASES)
@pytest.mark.parametrize("value", ["0.001", "0.005", "51.061"])
def test_posted_money_rejects_fractional_cents(schema, payload, value):
    with pytest.raises(ValidationError, match="decimal places"):
        schema.model_validate(
            {key: (value if item == "VALUE" else item) for key, item in payload.items()}
        )


@pytest.mark.parametrize("schema,payload", CASES)
@pytest.mark.parametrize("value", ["0.00", "51.06", "100"])
def test_posted_money_accepts_whole_cents(schema, payload, value):
    schema.model_validate(
        {key: (value if item == "VALUE" else item) for key, item in payload.items()}
    )
