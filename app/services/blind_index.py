# ============================================================================
# Blind indexes — querying a column you cannot read.
# ----------------------------------------------------------------------------
# Fernet output is randomized: the same plaintext encrypts to a different
# ciphertext every time. That is what you want for confidentiality and it is
# exactly what makes an encrypted column unqueryable — no WHERE, no ORDER BY,
# no unique constraint. app/services/encryption.py says so in as many words.
#
# A blind index is the standard way out. Alongside the encrypted column sits a
# second, DETERMINISTIC column holding a keyed hash of the same value:
#
#     bidx = HMAC-SHA256(index_key, "b1|<domain>|<normalized value>")
#
# Equal plaintexts produce equal hashes, so `WHERE kind_bidx = <hash>` works
# and can be indexed. The application computes the hash because it holds the
# key; a reader of the table cannot.
#
# WHAT A BLIND INDEX LEAKS. This is the part that decides whether a column is
# a sensible candidate, so it is worth being precise:
#
#   * Nothing directly. Without the key an attacker cannot compute the hash of
#     a guess, so they cannot invert a value by building a lookup table.
#   * EQUALITY. Rows sharing a value are visibly grouped. That is the whole
#     mechanism; it cannot be avoided.
#   * FREQUENCY. Bucket sizes are visible. Over a small value domain with a
#     skewed distribution that is close to plaintext: on `benefit_plans.kind`
#     the biggest bucket is almost certainly MEDICAL, and an attacker who
#     knows the domain will guess it correctly. It still costs them
#     DENTAL-vs-VISION-vs-LIFE, which they could previously just read.
#
# So a blind index is strong for high-cardinality, unguessable values and only
# partial for enums and flags. Truncating the hash to induce deliberate
# collisions (the usual mitigation, with the application filtering false
# positives after decryption) blurs frequency for HIGH-cardinality columns; it
# does nothing for a six-value enum, which is why this module does not
# truncate. Where a column is weak, the honest move is to document the
# residual leak rather than imply the problem is gone — see
# docs/hipaa-compliance.md § 164.312(a)(2)(iv).
#
# DOMAIN SEPARATION. The column's identity is inside the hash, so
# HMAC of "medical" in one column never equals HMAC of "medical" in another.
# Without that, an attacker could correlate values across tables even while
# unable to read any of them.
#
# KEYS. PAYROLL_BLIND_INDEX_SECRET if set, otherwise derived from
# PAYROLL_ENCRYPTION_SECRET with its own salt. Unlike the checkpoint signing
# key, this one cannot be optional — queries depend on it — so it falls back
# rather than failing. A separate value is still better: leaking the index key
# lets an attacker test guesses, while leaking the encryption key lets them
# read everything, and there is no reason to couple those.
#
# ROTATION rewrites every index column, because the hashes change:
#
#     PAYROLL_BLIND_INDEX_SECRET=<new>  python -m app.services.blind_index reindex
#
# There is no dual-key read path on purpose. A blind index is derived data: it
# can always be rebuilt from the plaintext the application can still decrypt,
# so the simple thing (recompute everything) is also the correct thing.
# ============================================================================

import hashlib
import hmac
import logging
import os
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import event

from app.config import PAYROLL_ENCRYPTION_SECRET

logger = logging.getLogger(__name__)

# Version tag inside the hashed material. Bump if normalization changes, so an
# old index value can never be compared against a new one as though they meant
# the same thing.
VERSION = "b1"

# Hex chars stored. 64 = the full SHA-256 digest: no collisions, so a lookup
# needs no post-filter. See the header on why truncation is not used here.
INDEX_LENGTH = 64

# Domain-separation salt, so an index key derived from the encryption secret is
# not the encryption key.
_DERIVATION_SALT = "slowbooks-blind-index-v1"


def _index_key() -> bytes:
    explicit = os.environ.get("PAYROLL_BLIND_INDEX_SECRET", "").strip()
    if explicit:
        return explicit.encode("utf-8")
    return hashlib.sha256(
        (_DERIVATION_SALT + "|" + PAYROLL_ENCRYPTION_SECRET).encode("utf-8")
    ).digest()


def normalize(value: Any) -> str | None:
    """Reduce a value to the one string form its hash is taken over.

    Two values that the application treats as equal must normalize to the same
    string, or the index will miss rows. Enums use their `.value` (the wire
    form the API speaks), dates their ISO-8601 form, strings are stripped and
    case-folded — a carrier written "Blue Shield" and " blue shield " should
    match, and nothing in this app treats case as meaningful in a lookup.
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    text = str(value).strip()
    if text == "":
        return None
    return text.casefold()


def blind_index(domain: str, value: Any) -> str | None:
    """The deterministic index value for `value` in column `domain`.

    `domain` is the qualified column name ("benefit_plans.kind"). Returns None
    for an absent value, so a NULL plaintext stays a NULL index and `IS NULL`
    keeps working on both.
    """
    normalized = normalize(value)
    if normalized is None:
        return None
    material = f"{VERSION}|{domain}|{normalized}".encode("utf-8")
    digest = hmac.new(_index_key(), material, hashlib.sha256).hexdigest()
    return digest[:INDEX_LENGTH]


# --- keeping the index in sync ----------------------------------------------
#
# Registered per (model, source column) rather than recomputed at call sites.
# A blind index that a single code path forgets to write is worse than none at
# all: the row becomes invisible to the query that filters on it, and nothing
# raises. Mapper-level events cannot be forgotten.

_REGISTERED: dict[tuple[str, str], str] = {}


def register_blind_index(model, source: str, index: str, domain: str) -> None:
    """Keep `model.index` equal to blind_index(domain, model.source).

    Fires on insert and on update, so editing the source value re-derives the
    index in the same flush.
    """
    _REGISTERED[(model.__tablename__, source)] = index

    def _sync(mapper, connection, target):  # noqa: ARG001 - SQLAlchemy signature
        setattr(target, index, blind_index(domain, getattr(target, source)))

    event.listen(model, "before_insert", _sync)
    event.listen(model, "before_update", _sync)


def registered_indexes() -> dict:
    """{(table, source column): index column} — what reindex_all walks."""
    return dict(_REGISTERED)


def reindex_all(db, dry_run: bool = False) -> dict:
    """Recompute every registered blind index from its plaintext.

    Run after rotating PAYROLL_BLIND_INDEX_SECRET, or after a migration that
    added a blind-index column to a table that already has rows.

    Reading the source attribute decrypts it through the ORM type, and an
    EncryptedString/EncryptedEnum returns None both for a genuinely NULL column
    and for ciphertext it cannot decrypt. Those two cases must not be treated
    alike: writing a NULL index for an undecryptable row would drop it out of
    every query that filters on the index, silently. So the raw column is read
    with SQL as well — a non-empty raw value that decrypts to None is counted
    under `failed` and its existing index is left untouched.

    Returns {"checked": N, "rewritten": N, "unchanged": N, "failed": N}.
    """
    import sqlalchemy as sa

    summary = {"checked": 0, "rewritten": 0, "unchanged": 0, "failed": 0}

    for (table, source), index in sorted(_REGISTERED.items()):
        model = _model_for_table(table)
        if model is None:
            logger.error("reindex: no model registered for table %r", table)
            summary["failed"] += 1
            continue
        domain = f"{table}.{source}"
        for row in db.query(model).all():
            summary["checked"] += 1
            plaintext = getattr(row, source)
            if plaintext is None:
                stored = db.execute(
                    sa.text(f"SELECT {source} FROM {table} WHERE id = :i"),
                    {"i": row.id},
                ).scalar()
                if stored:
                    summary["failed"] += 1
                    logger.error(
                        "reindex: %s #%s %s did not decrypt — index left as-is",
                        table,
                        row.id,
                        source,
                    )
                    continue
            expected = blind_index(domain, plaintext)
            if getattr(row, index) == expected:
                summary["unchanged"] += 1
                continue
            if not dry_run:
                setattr(row, index, expected)
            summary["rewritten"] += 1

    if not dry_run and summary["rewritten"]:
        db.commit()
    return summary


def _model_for_table(table: str):
    from app.database import Base

    for mapper in Base.registry.mappers:
        if mapper.class_.__tablename__ == table:
            return mapper.class_
    return None


def _cli() -> None:
    """`python -m app.services.blind_index reindex` — after key rotation."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m app.services.blind_index")
    sub = parser.add_subparsers(dest="cmd")
    reindex = sub.add_parser(
        "reindex", help="Recompute every blind index from its plaintext"
    )
    reindex.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.cmd != "reindex":
        parser.print_help()
        sys.exit(2)

    import app.models  # noqa: F401 - registers every model and its listeners
    from app.database import SessionLocal

    # Deliberately called through the fully-qualified module rather than the
    # local name. See the __main__ guard below for why.
    from app.services.blind_index import reindex_all as _reindex_all

    db = SessionLocal()
    try:
        result = _reindex_all(db, dry_run=args.dry_run)
    finally:
        db.close()

    for key in ("checked", "unchanged", "rewritten", "failed"):
        print(f"  {key:<10}: {result[key]}")
    if args.dry_run:
        print("  (dry-run, nothing committed)")
    sys.exit(1 if result["failed"] else 0)


if __name__ == "__main__":
    # `python -m app.services.blind_index` loads this file as __main__, so
    # importing app.models — which does `from app.services.blind_index import
    # register_blind_index` — loads a SECOND copy of it under its real name.
    # The registrations land in that copy's _REGISTERED; __main__'s stays
    # empty, and reindex silently reports "checked: 0" while every index stays
    # stale. Reaching for the canonical module is what makes the two agree.
    from app.services.blind_index import _cli as _canonical_cli

    _canonical_cli()
