# ============================================================================
# Saved company ACH origination details + who may use them.
#
# The four values live encrypted in the settings table and are excluded
# from get_all_settings(), so /api/settings never returns them. Reading
# them in full takes the bank-details permission plus a fresh password.
# ============================================================================

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models.users import ROLE_ADMIN, ROLE_READONLY, User
from app.services.settings_service import get_decrypted_setting, set_setting

FIELDS = (
    "immediate_destination",
    "immediate_origin",
    "originating_dfi_id",
    "company_account",
)


def _key(field: str) -> str:
    return f"ach_{field}"


def load(db: Session) -> dict:
    return {f: get_decrypted_setting(db, _key(f)) for f in FIELDS}


def save(db: Session, values: dict) -> None:
    """Store the given fields; a field left out keeps its saved value."""
    for f in FIELDS:
        value = values.get(f)
        if value is not None:
            set_setting(db, _key(f), value.strip())


def masked(saved: dict) -> dict:
    return {f: ("•••• " + v[-4:] if v else "") for f, v in saved.items()}


def is_configured(saved: dict) -> bool:
    return all(saved.get(f) for f in FIELDS)


def _session_user(request: Request, db: Session):
    uid = request.session.get("user_id")
    return db.query(User).filter(User.id == uid).first() if uid else None


def can_access(request: Request, db: Session) -> bool:
    """Admins always; bookkeepers with the flag; read-only users and API
    tokens never."""
    if getattr(request.state, "token_principal", None):
        return False
    if not request.session.get("authenticated"):
        return False
    user = _session_user(request, db)
    if user is None:
        # Legacy single-operator session: the operator is the admin.
        return (request.session.get("role") or ROLE_ADMIN) == ROLE_ADMIN
    if not user.is_active or user.role == ROLE_READONLY:
        return False
    return user.role == ROLE_ADMIN or bool(user.can_access_bank_details)


def require_access(request: Request, db: Session) -> None:
    if not can_access(request, db):
        raise HTTPException(
            status_code=403,
            detail="Your account doesn't have access to bank details. "
            "An admin can grant it under Settings → Users.",
        )


def verify_password(request: Request, db: Session, password: str) -> bool:
    from app.services.auth import check_password
    from app.services.auth import verify_password as _verify

    user = _session_user(request, db)
    if user is None:
        return check_password(db, password)
    return _verify(password, user.password_hash)


def originating_for_export(request: Request, db: Session, body: dict, pay_date):
    """Fill an ACH export's origination from the saved details.

    The file carries every payee's full account number, so producing one
    takes the same permission as reading the saved details.
    """
    from app.services.settings_service import company_identity

    require_access(request, db)
    saved = load(db)
    orig = dict(body)
    for f in FIELDS:
        if not orig.get(f):
            orig[f] = saved[f]
    missing = [f for f in FIELDS if not orig.get(f)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail="Save your company's ACH details first (missing: "
            + ", ".join(m.replace("_", " ") for m in missing)
            + ").",
        )
    co = company_identity(db)
    orig["effective_date"] = orig.get("effective_date") or pay_date
    orig["company_name"] = orig.get("company_name") or co["name"]
    orig["company_id"] = orig.get("company_id") or co["ein"]
    return orig


def record_export(db: Session, table: str, run_id: int) -> None:
    from app.services.audit import log_event

    log_event(db, table, run_id, "ACH_EXPORT")
    db.commit()
