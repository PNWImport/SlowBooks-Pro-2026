"""Encryption is real on disk, and key rotation covers all of it.

Two failure modes that ordinary tests cannot see, because the ORM decrypts
transparently on read — a column can be declared encrypted, pass every
functional test, and still be sitting in plaintext:

1. The value is not actually ciphertext in the column. Proven here by
   reading the raw column with SQL, bypassing the TypeDecorator.

2. The column is encrypted but missing from `rewrap_all`'s TYPED_TARGETS.
   That survives normal operation and then becomes permanently unreadable
   the first time the key is rotated, because nothing re-wraps it under the
   new key. Proven here by walking the model metadata and requiring every
   encrypted column to be listed.

The second one is the dangerous one: the damage appears at rotation time,
long after the change that caused it.
"""

from sqlalchemy import text

from app.database import Base
import app.models  # noqa: F401 — registers every model
from app.services.encryption import (
    _VERSION_PREFIX,
    EncryptedDate,
    EncryptedEnum,
    EncryptedString,
)

ENCRYPTED_TYPES = (EncryptedString, EncryptedDate, EncryptedEnum)


def _declared_encrypted_columns() -> set[tuple[str, str]]:
    """(table, column) for every column using an encrypting TypeDecorator."""
    found = set()
    for mapper in Base.registry.mappers:
        for column in mapper.local_table.columns:
            if isinstance(column.type, ENCRYPTED_TYPES):
                found.add((mapper.local_table.name, column.name))
    return found


def _rewrap_covered_columns() -> set[tuple[str, str]]:
    """(table, column) that rewrap_all would actually re-encrypt.

    Parsed out of the function source rather than executed, so this needs no
    database and stays honest if the list is edited by hand.
    """
    import inspect as py_inspect
    import re

    from app.services import encryption

    src = py_inspect.getsource(encryption.rewrap_all)
    block = src[
        src.index("TYPED_TARGETS = [") : src.index("]", src.index("TYPED_TARGETS = ["))
    ]

    model_tables = {
        m.class_.__name__: m.local_table.name for m in Base.registry.mappers
    }
    covered = set()
    for model_name, fields in re.findall(r"\((\w+),\s*\(([^)]*)\)", block):
        table = model_tables.get(model_name)
        if not table:
            continue
        for field in re.findall(r'"(\w+)"', fields):
            covered.add((table, field))
    return covered


def test_every_encrypted_column_is_rewrapped_on_key_rotation():
    missing = _declared_encrypted_columns() - _rewrap_covered_columns()
    assert not missing, (
        "Encrypted columns missing from rewrap_all's TYPED_TARGETS. These "
        "become unreadable the first time PAYROLL_ENCRYPTION_SECRET is "
        "rotated:\n  " + "\n  ".join(f"{t}.{c}" for t, c in sorted(missing))
    )


def test_rewrap_list_has_no_phantom_columns():
    """A stale entry means rotation walks a column that no longer exists."""
    phantom = _rewrap_covered_columns() - _declared_encrypted_columns()
    # Raw *_enc columns are handled by RAW_TARGETS, not TYPED_TARGETS, so
    # they legitimately do not appear in the declared-encrypted set.
    phantom = {(t, c) for t, c in phantom if not c.endswith("_enc")}
    assert (
        not phantom
    ), "TYPED_TARGETS names columns that are not encrypted:\n  " + "\n  ".join(
        f"{t}.{c}" for t, c in sorted(phantom)
    )


def test_employee_pii_is_ciphertext_on_disk(client, db_session):
    """The ORM would hide plaintext. Read the raw column with SQL."""
    resp = client.post(
        "/api/employees",
        json={
            "first_name": "Raw",
            "last_name": "Check",
            "pay_type": "salary",
            "pay_rate": 50000,
            "pay_frequency": "biweekly",
            "filing_status": "single",
            "work_state": "WA",
            "ssn_last_four": "6789",
            "address1": "500 Secret Lane",
        },
    )
    assert resp.status_code == 201, resp.text
    emp_id = resp.json()["id"]

    row = db_session.execute(
        text("SELECT ssn_last_four, address1 FROM employees WHERE id = :i"),
        {"i": emp_id},
    ).first()

    # Ciphertext carries the rotation version prefix, e.g. "v1:gAAAAA...".
    assert row.ssn_last_four != "6789", "SSN stored in plaintext"
    assert row.ssn_last_four.startswith(
        _VERSION_PREFIX
    ), "SSN is not versioned ciphertext"
    assert "Secret Lane" not in (row.address1 or ""), "address stored in plaintext"
    assert row.address1.startswith(
        _VERSION_PREFIX
    ), "address is not versioned ciphertext"

    # And it still round-trips through the ORM.
    got = client.get(f"/api/employees/{emp_id}").json()
    assert got["ssn_last_four"] == "6789"


def test_vendor_tax_id_is_ciphertext_on_disk(client, db_session):
    resp = client.post(
        "/api/vendors", json={"name": "TIN Vendor", "tax_id": "12-3456789"}
    )
    assert resp.status_code == 201, resp.text
    vid = resp.json()["id"]

    raw = db_session.execute(
        text("SELECT tax_id FROM vendors WHERE id = :i"), {"i": vid}
    ).scalar()

    assert raw != "12-3456789", "taxpayer ID stored in plaintext"
    assert raw.startswith(_VERSION_PREFIX)
    assert client.get(f"/api/vendors/{vid}").json()["tax_id"] == "12-3456789"
