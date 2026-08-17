# ============================================================================
# Field-level encryption for payroll PII (employee bank routing / account #s).
#
# Ciphertext is versioned with a "v{N}:" prefix so the active key can be
# rotated without a destructive re-encrypt:
#
#   PAYROLL_ENCRYPTION_SECRET       — current key, used to encrypt + try first
#                                     on decrypt
#   PAYROLL_ENCRYPTION_SECRET_PREV  — optional, last rotated-out key, used
#                                     only on decrypt
#
# Rotation procedure:
#   1. Move the live secret into PAYROLL_ENCRYPTION_SECRET_PREV.
#   2. Set the new secret as PAYROLL_ENCRYPTION_SECRET.
#   3. Bounce the app — new writes go out under the new key; old reads
#      transparently fall through to the previous key.
#   4. Run `python -m app.services.encryption rewrap` (offline) to re-encrypt
#      every stored ciphertext under the new key.
#   5. Drop PAYROLL_ENCRYPTION_SECRET_PREV.
# ============================================================================

import base64
import logging
from datetime import date as _date
import os

from cryptography.fernet import Fernet, InvalidToken
import sqlalchemy as sa
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import PAYROLL_ENCRYPTION_SECRET

logger = logging.getLogger(__name__)

# Static salt — fine here because the secret itself is the protected material;
# rotating the secret rotates the derived key.
_SALT = b"slowbooks-payroll-v1"

# Version 1: current scheme. Bump if we ever change algorithm or salt.
_CURRENT_VERSION = 1
_VERSION_PREFIX = f"v{_CURRENT_VERSION}:"


def _derive_fernet(secret: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
    return Fernet(key)


def _active_fernets() -> list[Fernet]:
    """Build the decrypt-key chain: current first, then previous (if set)."""
    keys = [_derive_fernet(PAYROLL_ENCRYPTION_SECRET)]
    prev = os.environ.get("PAYROLL_ENCRYPTION_SECRET_PREV", "").strip()
    if prev and prev != PAYROLL_ENCRYPTION_SECRET:
        keys.append(_derive_fernet(prev))
    return keys


_fernets = _active_fernets()


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a string for storage. Returns None for empty input."""
    if plaintext is None or plaintext == "":
        return None
    token = _fernets[0].encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _VERSION_PREFIX + token


def decrypt(token: str | None) -> str | None:
    """Decrypt a stored value. Tries the current key first, then any
    rotated-out previous key. Returns None for empty or undecryptable input."""
    if not token:
        return None

    raw = token[len(_VERSION_PREFIX) :] if token.startswith(_VERSION_PREFIX) else token

    for fernet in _fernets:
        try:
            return fernet.decrypt(raw.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            continue

    logger.error("Failed to decrypt a stored secret with any configured key")
    return None


# --- transparent column types ----------------------------------------------
#
# Wrapping a column in one of these encrypts on the way to the database and
# decrypts on the way back, so call sites read and write plaintext and the
# ciphertext never leaves this module. Used for the ePHI surface the benefits
# module introduced (carrier name, dependent identifiers).
#
# TRADE-OFF: Fernet output is randomized, so an encrypted column cannot be
# filtered, sorted, grouped or uniquely indexed in SQL. Only wrap columns the
# application reads whole. Anything that needs a WHERE clause needs either a
# separate blind index or to stay plaintext.


class EncryptedString(TypeDecorator):
    """A Unicode column stored as Fernet ciphertext."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return None
        return encrypt(str(value))

    def process_result_value(self, value, dialect):
        if not value:
            return None
        plaintext = decrypt(value)
        if plaintext is None and value:
            # Undecryptable ciphertext: decrypt() has already logged. Return
            # None rather than raising so one unreadable row cannot take down
            # a whole payroll or ACA run — the absence is visible in output.
            return None
        return plaintext


class EncryptedDate(TypeDecorator):
    """A Date column stored as an ISO-8601 string in Fernet ciphertext.

    Dates of birth are identifiers under HIPAA's safe-harbor list, so a
    dependent's DOB gets the same treatment as their name.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            value = _date.fromisoformat(value)
        return encrypt(value.isoformat())

    def process_result_value(self, value, dialect):
        if not value:
            return None
        plaintext = decrypt(value)
        if not plaintext:
            return None
        try:
            return _date.fromisoformat(plaintext)
        except ValueError:
            logger.error("Encrypted date column held an unparseable value")
            return None


class EncryptedEnum(TypeDecorator):
    """A Python enum stored as its `.value` in Fernet ciphertext.

    Replaces a native PostgreSQL enum, which cannot be encrypted at all — the
    database refuses any value outside the declared label set, and ciphertext
    is never one of them.

    A column that was a native enum is almost always one somebody filters on,
    so pair this with a blind index (see app/services/blind_index.py). Note
    what that concedes: a small label set means bucket sizes are visible, so
    the most common value is guessable. Encrypting a six-way enum buys
    confidentiality against reading, not against counting.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_class, *args, **kwargs):
        # The attribute name must match the constructor parameter name:
        # SQLAlchemy builds this type's cache key by looking up each __init__
        # argument on the instance.
        self.enum_class = enum_class
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return None
        if isinstance(value, self.enum_class):
            value = value.value
        return encrypt(str(value))

    def process_result_value(self, value, dialect):
        if not value:
            return None
        plaintext = decrypt(value)
        if not plaintext:
            return None
        try:
            return self.enum_class(plaintext)
        except ValueError:
            logger.error(
                "Encrypted enum column held %r, which is not a %s member",
                plaintext,
                self.enum_class.__name__,
            )
            return None


def _is_encrypted_with_current(token: str) -> bool:
    """True if the value decrypts under the CURRENT key. False if it
    decrypts only under the previous key, or doesn't decrypt at all."""
    if not token:
        return True  # nothing to rewrap
    raw = token[len(_VERSION_PREFIX) :] if token.startswith(_VERSION_PREFIX) else token
    try:
        _fernets[0].decrypt(raw.encode("ascii"))
        return True
    except (InvalidToken, ValueError):
        return False


def rewrap_all(db, dry_run: bool = False) -> dict:
    """Re-encrypt every stored ciphertext under the CURRENT key.

    Iterates every row in every model that stores a Fernet ciphertext:
    EmployeeBankAccount, VendorBankAccount, and the benefits ePHI columns
    (BenefitPlan.{carrier_name, kind}, BenefitEnrollment.{coverage_start,
    coverage_end}, BenefitDependent.{name, ssn_last_four, dob}).
    A field missing from this list survives rotation only until the previous
    key is dropped, so keep it in sync when a new encrypted column lands —
    tests/test_benefits_encryption.py asserts the coverage.

    Blind-index columns are NOT touched here: they are keyed by the blind-index
    secret, not the encryption secret, so rotating one has no effect on the
    other. Rotating the index key is
    `python -m app.services.blind_index reindex`.
    For each value:
      - if it decrypts under the current key, skip (already rewrapped)
      - if it decrypts under PREV, re-encrypt with current and update
      - if it doesn't decrypt at all, log + count as a failure (don't wipe)

    Use this after rotating the secret. Returns a summary dict:
      {"checked": N, "rewrapped": N, "already_current": N, "failed": N}

    `dry_run=True` runs the same scan and reports what WOULD change
    without committing.
    """
    from sqlalchemy import inspect as sa_inspect

    from app.models.bank_accounts import EmployeeBankAccount
    from app.models.benefits import BenefitDependent, BenefitEnrollment, BenefitPlan
    from app.models.contractor_payments import VendorBankAccount

    summary = {"checked": 0, "rewrapped": 0, "already_current": 0, "failed": 0}

    # (model, [raw ciphertext column names]) — these hold the ciphertext
    # directly, so read/write bypasses the TypeDecorator.
    RAW_TARGETS = [
        (EmployeeBankAccount, ("routing_number_enc", "account_number_enc")),
        (VendorBankAccount, ("routing_number_enc", "account_number_enc")),
    ]
    # (model, [columns wrapped in EncryptedString/EncryptedDate]) — the ORM
    # decrypts these on read, so rewrapping means reading the plaintext and
    # writing it straight back: the bind processor re-encrypts under the
    # current key.
    TYPED_TARGETS = [
        (BenefitPlan, ("carrier_name", "kind")),
        (BenefitEnrollment, ("coverage_start", "coverage_end")),
        (BenefitDependent, ("name", "ssn_last_four", "dob")),
    ]

    for model, fields in RAW_TARGETS:
        for row in db.query(model).all():
            for field in fields:
                blob = getattr(row, field)
                if not blob:
                    continue
                summary["checked"] += 1
                if _is_encrypted_with_current(blob):
                    summary["already_current"] += 1
                    continue
                plaintext = decrypt(blob)
                if plaintext is None:
                    summary["failed"] += 1
                    logger.error(
                        "rewrap: %s #%s field %s did not decrypt under any key",
                        model.__tablename__,
                        row.id,
                        field,
                    )
                    continue
                if not dry_run:
                    setattr(row, field, encrypt(plaintext))
                summary["rewrapped"] += 1

    for model, fields in TYPED_TARGETS:
        for row in db.query(model).all():
            state = sa_inspect(row)
            for field in fields:
                # Read the stored ciphertext without the type's decryption,
                # so "already under the current key" can be answered.
                blob = db.execute(
                    sa.text(f"SELECT {field} FROM {model.__tablename__} WHERE id = :i"),
                    {"i": row.id},
                ).scalar()
                if not blob:
                    continue
                summary["checked"] += 1
                if _is_encrypted_with_current(blob):
                    summary["already_current"] += 1
                    continue
                plaintext = getattr(row, field)  # decrypts via the type
                if plaintext is None:
                    summary["failed"] += 1
                    logger.error(
                        "rewrap: %s #%s field %s did not decrypt under any key",
                        model.__tablename__,
                        row.id,
                        field,
                    )
                    continue
                if not dry_run:
                    # Re-assign so the bind processor re-encrypts under the
                    # current key; force the flush even though the decrypted
                    # value compares equal to itself.
                    setattr(row, field, plaintext)
                    state.attrs[field].history  # noqa: B018 - mark dirty
                    db.add(row)
                    from sqlalchemy.orm.attributes import flag_modified

                    flag_modified(row, field)
                summary["rewrapped"] += 1

    if not dry_run:
        db.commit()
    return summary


def _cli():
    """`python -m app.services.encryption rewrap` — offline key rotation helper.

    Requires the database to be reachable and PAYROLL_ENCRYPTION_SECRET_PREV
    to be set if any rows are currently encrypted under the old key. Exits
    non-zero if any row fails to decrypt under either key.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m app.services.encryption")
    sub = parser.add_subparsers(dest="cmd")
    rewrap = sub.add_parser(
        "rewrap", help="Re-encrypt all stored ciphertext under the current key"
    )
    rewrap.add_argument(
        "--dry-run", action="store_true", help="Show what would change without writing"
    )
    args = parser.parse_args()

    if args.cmd != "rewrap":
        parser.print_help()
        sys.exit(2)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = rewrap_all(db, dry_run=args.dry_run)
    finally:
        db.close()

    print(f"  checked         : {result['checked']}")
    print(f"  already current : {result['already_current']}")
    print(
        f"  rewrapped       : {result['rewrapped']}{' (dry-run, not committed)' if args.dry_run else ''}"
    )
    print(f"  failed          : {result['failed']}")
    sys.exit(1 if result["failed"] > 0 else 0)


if __name__ == "__main__":
    _cli()
