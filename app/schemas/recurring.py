from datetime import date
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator

from app.schemas.common import (
    StrictModel,
    TaxRateFloat,
    validate_non_negative_line,
)


class RecurringLineCreate(StrictModel):
    item_id: Optional[int] = None
    description: Optional[str] = None
    quantity: float = 1
    rate: float = 0
    is_taxable: Optional[bool] = None
    line_order: int = 0

    @model_validator(mode="after")
    def _check_non_negative(self):
        validate_non_negative_line(self.quantity, self.rate)
        return self


class RecurringLineResponse(BaseModel):
    id: int
    item_id: Optional[int] = None
    description: Optional[str] = None
    quantity: float = 1
    rate: float = 0
    is_taxable: bool = True
    line_order: int = 0
    model_config = {"from_attributes": True}


class RecurringCreate(StrictModel):
    customer_id: int
    frequency: str  # weekly, monthly, quarterly, yearly
    start_date: date
    end_date: Optional[date] = None
    terms: str = "Net 30"
    tax_rate: TaxRateFloat = 0
    notes: Optional[str] = None
    class_id: Optional[int] = None
    job_id: Optional[int] = None
    lines: list[RecurringLineCreate] = []

    @field_validator("lines")
    @classmethod
    def _require_lines(cls, v):
        if not v:
            raise ValueError("recurring invoice must have at least one line")
        return v

    @field_validator("frequency")
    @classmethod
    def _frequency(cls, value):
        value = (value or "").strip().lower()
        if value not in {"weekly", "monthly", "quarterly", "yearly"}:
            raise ValueError("frequency must be weekly, monthly, quarterly, or yearly")
        return value

    @model_validator(mode="after")
    def _date_order(self):
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class RecurringUpdate(StrictModel):
    frequency: Optional[str] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None
    terms: Optional[str] = None
    tax_rate: Optional[TaxRateFloat] = None
    notes: Optional[str] = None
    class_id: Optional[int] = None
    job_id: Optional[int] = None
    lines: Optional[list[RecurringLineCreate]] = None

    @field_validator("frequency")
    @classmethod
    def _frequency(cls, value):
        if value is None:
            raise ValueError("frequency cannot be null")
        value = value.strip().lower()
        if value not in {"weekly", "monthly", "quarterly", "yearly"}:
            raise ValueError("frequency must be weekly, monthly, quarterly, or yearly")
        return value


class RecurringResponse(BaseModel):
    id: int
    customer_id: int
    customer_name: Optional[str] = None
    frequency: str
    start_date: date
    end_date: Optional[date] = None
    next_due: date
    is_active: bool = True
    terms: Optional[str] = None
    tax_rate: float = 0
    notes: Optional[str] = None
    class_id: Optional[int] = None
    job_id: Optional[int] = None
    invoices_created: int = 0
    lines: list[RecurringLineResponse] = []
    model_config = {"from_attributes": True}
