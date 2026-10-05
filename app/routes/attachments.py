# ============================================================================
# Attachments — file upload/download for invoices, bills, etc.
# Phase 10: Quick Wins + Medium Effort Features
#
# The bytes are kept in the company's own database (stored_files, see
# app/services/file_store.py). They used to be written to
# uploads/attachments/<type>/<record id>/<name> in a folder every company on
# a desktop install shared, so company B's invoice 1 "receipt.pdf" replaced
# company A's, and deleting B's made A's answer 404 (2.18.0 gate, skytech).
# ============================================================================

import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attachments import Attachment
from app.schemas.attachments import AttachmentResponse
from app.services import file_store

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

# The record types a file can be attached to. The user-provided entity_type
# is routed through this dict, so only these words are ever stored. (It was
# also the folder name when attachments were files on disk.)
_ENTITY_TYPE_DIRS = {
    "invoice": "invoice",
    "bill": "bill",
    "expense": "expense",
    "estimate": "estimate",
    "purchase_order": "purchase_order",
    "vendor_credit": "vendor_credit",
    "vendor": "vendor",
    "customer": "customer",
}

# Whitelist of MIME types we accept for attachments. An attachment is served
# back under its stored type, so we reject anything that a browser would
# render and potentially execute (HTML, SVG with scripts, executables).
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "text/plain",
    "text/csv",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip",
}
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".txt",
    ".csv",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
}

# Only plain word chars, spaces, hyphens, dots, and parens in filenames.
# Everything else gets rewritten out: the name is shown in lists and sent in
# the download's Content-Disposition. Path(...).name strips any directory.
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9 ._()\-]")


def _sanitize_filename(raw: str) -> str:
    """Strip path separators and restrict to a safe character set."""
    base = Path(raw or "").name
    if not base or base.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip()
    # Belt and braces: even after Path(...).name, reject anything that still
    # contains path separators or parent refs.
    if not cleaned or cleaned.startswith(".") or "/" in cleaned or "\\" in cleaned:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return cleaned


def _split_stored_path(stored: str) -> list[str]:
    """Split a stored relative path on either separator.

    Rows written by a pre-fix Windows install carry backslashes; they must
    keep resolving on every platform.
    """
    # Normalizing legacy separators must not turn absolute paths into
    # apparently relative paths and bypass the existing rejection rule.
    from pathlib import PureWindowsPath

    if stored.startswith(("/", "\\")) or PureWindowsPath(stored).drive:
        raise HTTPException(status_code=400, detail="Invalid path")
    return [part for part in stored.replace("\\", "/").split("/") if part]


def _resolve_within(base: Path, *parts: str) -> Path:
    """Join parts onto base, resolve, and assert the result is inside base.


def _record_attachment(db: Session, attachment_id: int) -> Attachment | None:
    """An attachment on a record — never an employee document. Those share
    the table, and this route has none of their admin-only rule: a read-only
    sign-in could download a W-4 by its id here, or a bookkeeper delete one."""
    return (
        db.query(Attachment)
        .filter(
            Attachment.id == attachment_id,
            Attachment.employee_id.is_(None),
            Attachment.entity_type.in_(list(_ENTITY_TYPE_DIRS)),
        )
        .first()
    )


@router.post(
    "/{entity_type}/{entity_id}", response_model=AttachmentResponse, status_code=201
)
async def upload_attachment(
    entity_type: str,
    entity_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    _entity_type(entity_type)

    safe_filename = _sanitize_filename(file.filename or "")
    extension = Path(safe_filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{extension}' not allowed",
        )
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"MIME type '{file.content_type}' not allowed",
        )

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    # Build and verify paths against the upload base BEFORE any filesystem op.
    upload_dir = _resolve_within(UPLOAD_BASE, type_dir, str(entity_id))
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = _resolve_within(upload_dir, f"{uuid4().hex}{extension}")
    with file_path.open("xb") as uploaded:
        uploaded.write(content)

    attachment = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        filename=safe_filename,
        # POSIX form, always. str() on a WindowsPath yields backslashes, and
        # a company file written on Windows would then be unable to find its
        # own attachments when opened on macOS or Linux — joinpath() there
        # treats "uploads\\attachments\\x.pdf" as one filename.
        file_path=file_path.relative_to(STATIC_BASE).as_posix(),
        mime_type=file.content_type,
        file_size=len(content),
    )
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/download/{attachment_id}")
def download_attachment(attachment_id: int, db: Session = Depends(get_db)):
    attachment = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    file_path = _resolve_within(STATIC_BASE, *_split_stored_path(attachment.file_path))
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        str(file_path),
        filename=attachment.filename,
        media_type=attachment.mime_type or "application/octet-stream",
    )


@router.get("/{entity_type}/{entity_id}", response_model=list[AttachmentResponse])
def list_attachments(entity_type: str, entity_id: int, db: Session = Depends(get_db)):
    _entity_type(entity_type)
    return (
        db.query(Attachment)
        .filter(
            Attachment.entity_type == entity_type,
            Attachment.entity_id == entity_id,
            Attachment.employee_id.is_(None),
        )
        .order_by(Attachment.uploaded_at.desc(), Attachment.id.desc())
        .all()
    )


@router.delete("/{attachment_id}")
def delete_attachment(attachment_id: int, db: Session = Depends(get_db)):
    attachment = _record_attachment(db, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    file_path = _resolve_within(STATIC_BASE, *_split_stored_path(attachment.file_path))
    try:
        file_path.unlink()
    except FileNotFoundError:
        pass  # DB row present but file already gone — delete the row anyway

    db.delete(attachment)
    db.commit()
    return {"status": "deleted"}
