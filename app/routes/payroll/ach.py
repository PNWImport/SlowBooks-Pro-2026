# ============================================================================
# Company ACH origination details — saved once, masked on read.
#
#   GET  /api/payroll/ach-settings         masked values + whether the
#                                          caller may use them
#   PUT  /api/payroll/ach-settings         save (blank field = keep)
#   POST /api/payroll/ach-settings/reveal  full values; needs the caller's
#                                          password, rate-limited, audited
#
# Registered before runs.py: "/ach-settings" would otherwise hit /{run_id}.
# ============================================================================

import re
from datetime import date
from typing import Optional

from fastapi import Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.payroll._router import router
from app.schemas.common import StrictModel
from app.services import ach_settings
from app.services.audit import log_event
from app.services.nacha_export import validate_routing_number
from app.services.rate_limit import limiter


class AchOriginating(StrictModel):
    """ACH export body. Origination fields left out come from the saved
    details."""

    immediate_destination: str = ""
    immediate_origin: str = ""
    destination_name: str = "BANK"
    origin_name: str = ""
    company_name: str = ""
    company_id: str = ""
    originating_dfi_id: str = ""
    company_account: str = ""
    effective_date: Optional[date] = None


class AchSettingsUpdate(StrictModel):
    immediate_destination: Optional[str] = Field(None, max_length=20)
    immediate_origin: Optional[str] = Field(None, max_length=20)
    originating_dfi_id: Optional[str] = Field(None, max_length=20)
    company_account: Optional[str] = Field(None, max_length=30)


class RevealRequest(StrictModel):
    password: str = Field(..., min_length=1, max_length=512)


def _validate(data: AchSettingsUpdate) -> dict:
    values = {k: v.strip() for k, v in data.model_dump().items() if v and v.strip()}
    dest = values.get("immediate_destination")
    if dest is not None and not validate_routing_number(dest):
        raise HTTPException(
            status_code=400,
            detail="Bank routing number must be 9 digits and pass the ABA check",
        )
    origin = values.get("immediate_origin")
    if origin is not None and not re.fullmatch(r"\d{9,10}", origin):
        raise HTTPException(status_code=400, detail="Company ID must be 9 or 10 digits")
    dfi = values.get("originating_dfi_id")
    if dfi is not None and not re.fullmatch(r"\d{8}", dfi):
        raise HTTPException(
            status_code=400, detail="Originating bank ID must be 8 digits"
        )
    acct = values.get("company_account")
    if acct is not None and not re.fullmatch(r"[0-9A-Za-z-]{1,17}", acct):
        raise HTTPException(
            status_code=400,
            detail="Company account number must be 1-17 letters, digits or dashes",
        )
    return values


def _view(request: Request, db: Session) -> dict:
    saved = ach_settings.load(db)
    return {
        "configured": ach_settings.is_configured(saved),
        "can_access": ach_settings.can_access(request, db),
        "values": ach_settings.masked(saved),
    }


@router.get("/ach-settings")
def get_ach_settings(request: Request, db: Session = Depends(get_db)):
    return _view(request, db)


@router.put("/ach-settings")
def update_ach_settings(
    data: AchSettingsUpdate, request: Request, db: Session = Depends(get_db)
):
    ach_settings.require_access(request, db)
    ach_settings.save(db, _validate(data))
    db.commit()
    return _view(request, db)


@router.post("/ach-settings/reveal")
@limiter.limit("5/minute")
def reveal_ach_settings(
    payload: RevealRequest, request: Request, db: Session = Depends(get_db)
):
    ach_settings.require_access(request, db)
    # 403, not 401: the SPA treats any 401 as a dead session and signs out.
    if not ach_settings.verify_password(request, db, payload.password):
        raise HTTPException(status_code=403, detail="Incorrect password")
    log_event(db, "settings", 0, "REVEAL", new_values={"what": "ACH details"})
    db.commit()
    return {"values": ach_settings.load(db)}
