from datetime import date as dt_date, datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from app.schemas.common import StrictModel


class TimeEntryCreate(StrictModel):
    employee_id: int
    date: dt_date
    hours_regular: float = Field(default=0, ge=0, le=24)
    hours_overtime: float = Field(default=0, ge=0, le=24)
    hours_doubletime: float = Field(default=0, ge=0, le=24)
    project_id: Optional[int] = None
    job_id: Optional[int] = None
    cost_code_id: Optional[int] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _valid_daily_total(self):
        total = self.hours_regular + self.hours_overtime + self.hours_doubletime
        if total <= 0 or total > 24:
            raise ValueError("daily hours must be greater than 0 and at most 24")
        return self


class TimeEntryUpdate(StrictModel):
    date: Optional[dt_date] = None
    hours_regular: Optional[float] = Field(default=None, ge=0, le=24)
    hours_overtime: Optional[float] = Field(default=None, ge=0, le=24)
    hours_doubletime: Optional[float] = Field(default=None, ge=0, le=24)
    project_id: Optional[int] = None
    job_id: Optional[int] = None
    cost_code_id: Optional[int] = None
    notes: Optional[str] = None
    status: Optional[str] = None

    @field_validator(
        "date",
        "hours_regular",
        "hours_overtime",
        "hours_doubletime",
    )
    @classmethod
    def _required_values_cannot_be_cleared(cls, value):
        # These fields are optional only because this is a PATCH-like update
        # model. If supplied, they still map to non-null business values.
        if value is None:
            raise ValueError("field cannot be null")
        return value


class TimeEntryResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: Optional[str] = None
    date: dt_date
    hours_regular: float = 0
    hours_overtime: float = 0
    hours_doubletime: float = 0
    project_id: Optional[int] = None
    job_id: Optional[int] = None
    cost_code_id: Optional[int] = None
    job_name: Optional[str] = None
    cost_code_label: Optional[str] = None
    job_cost_id: Optional[int] = None
    notes: Optional[str] = None
    status: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    pay_run_id: Optional[int] = None
    model_config = {"from_attributes": True}


class TimeEntryApprove(StrictModel):
    approved_by: str = "manager"
