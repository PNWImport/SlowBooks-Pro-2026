from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field
from app.schemas.common import Money, StrictModel


class BudgetCreate(StrictModel):
    account_id: int
    year: int
    month: int = Field(ge=1, le=12)
    amount: Money = Decimal("0")


class BudgetUpdate(BaseModel):
    amount: Optional[Money] = None


class BudgetResponse(BaseModel):
    id: int
    account_id: int
    year: int
    month: int
    amount: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
