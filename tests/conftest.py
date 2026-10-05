# ============================================================================
# Slowbooks Pro 2026 — pytest configuration
#
# Each test gets a fresh in-memory SQLite database via the db_engine fixture.
# The `client` fixture wires the app's get_db dependency to that same engine
# so API calls and direct db_session queries hit the same tables.
# Rate limiting is disabled by default so per-test counters don't collide.
# ============================================================================

import os
import sys
from decimal import Decimal
from pathlib import Path

# ---- Environment overrides (must run BEFORE any app imports) ----
os.environ["APP_DEBUG"] = "true"  # Disable production security checks in test
os.environ["SESSION_SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ALLOWED_ORIGINS"] = "http://testserver,http://localhost:3001"
os.environ["CORS_ALLOW_ORIGINS"] = "http://testserver,http://localhost:3001"
os.environ["RATE_LIMIT_ENABLED"] = "0"
os.environ["SESSION_IDLE_TIMEOUT_SECONDS"] = "0"  # Disable idle expiry in tests
# The suite is written against tesseract; on a Mac/Windows dev box with the
# native OCR bridge installed, auto-selection would pick Vision/WinRT and
# bypass the ocr_service monkeypatches. Selection tests override per-test.
os.environ.setdefault("SLOWBOOKS_OCR_ENGINE", "tesseract")
# Point the app at an in-memory DB by default; fixtures override per-test.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Uploads, attachments and backups go to a throwaway directory, never the
# checkout's app/static/uploads or backups/ (a developer's real files on a
# working install). Tests of the override itself set or clear it per-test.
if "SLOWBOOKS_DATA_DIR" not in os.environ:
    import tempfile as _tempfile

    os.environ["SLOWBOOKS_DATA_DIR"] = _tempfile.mkdtemp(prefix="slowbooks-test-data-")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

# ---------------------------------------------------------------------------
# WeasyPrint's native stack (issue #121)
#
# Rendering a PDF needs pango/cairo/gobject. Importing the app no longer does
# (app/services/pdf_service.py imports WeasyPrint lazily), so the suite runs
# on a machine without them — which matters because CI runs pytest on Linux
# only, and the Windows box that would have caught @wilsons043's encoding bug
# could not import the app at all.
#
# A test that actually renders still cannot pass without the stack. Rather
# than guess which tests those are with a marker anyone can forget, we let
# the test run and turn the library's own ImportError into a SKIP — so a test
# skips exactly when it needed the missing library, and never otherwise.
# ---------------------------------------------------------------------------

try:  # noqa: SIM105
    import weasyprint as _weasyprint  # noqa: F401

    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False


def _is_missing_native_stack(exc: BaseException) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (ImportError, OSError)):
            text = str(exc).lower()
            if (
                "weasyprint" in text
                or "gobject" in text
                or "pango" in text
                or "cairo" in text
            ):
                return True
        exc = exc.__cause__ or exc.__context__
    return False


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    outcome = yield
    if WEASYPRINT_AVAILABLE:
        return
    exc = outcome.excinfo[1] if getattr(outcome, "excinfo", None) else None
    if exc is not None and _is_missing_native_stack(exc):
        outcome.force_exception(
            pytest.skip.Exception(
                "needs WeasyPrint's native stack (pango/cairo/gobject), which "
                "is not installed on this machine — the rest of the suite runs"
            )
        )


from starlette.requests import HTTPConnection  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

# Import all model modules so Base.metadata sees every table before create_all.
# Without these imports, tables defined in unimported modules wouldn't be created.
from app.models import (  # noqa: F401,E402
    accounts,
    attachments,
    audit,
    auth as auth_model,
    backups,
    banking,
    bank_accounts,
    bank_rules,
    bills,
    budgets,
    companies,
    contacts,
    credit_memos,
    vendor_credits,
    deductions,
    document_audit as document_audit_model,
    email_log,
    email_templates,
    portal_access as portal_access_model,
    reseller_permit as reseller_permit_model,
    estimates,
    hr,
    invoices,
    in_kind as in_kind_model,
    items,
    nonprofit as nonprofit_model,
    payments,
    payroll,
    pto,
    purchase_orders,
    qbo_mapping,
    recurring,
    settings as settings_model,
    tax,
    time_entries,
    transactions,
)
import app.database as db_module  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.seed.chart_of_accounts import CHART_OF_ACCOUNTS  # noqa: E402

from app.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Per-test in-memory engine — every test gets a clean slate
# ---------------------------------------------------------------------------


_SUITE_SESSION_FACTORY = sessionmaker(autocommit=False, autoflush=False)


def _shared_factory(engine):
    """Reuse listener registration while retaining a fresh engine per test."""
    from app.services.audit import register_audit_hooks

    _SUITE_SESSION_FACTORY.configure(bind=engine)
    register_audit_hooks(_SUITE_SESSION_FACTORY)
    return _SUITE_SESSION_FACTORY


@pytest.fixture
def db_engine():
    """Per-test in-memory SQLite engine with full schema."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    # Route and direct-service sessions share this isolated DB and the same
    # long-lived audit-hook target; no per-test listener targets accumulate.
    db_module.engine = engine
    db_module.SessionLocal = _shared_factory(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def TestSession(db_engine):
    """Shared factory, bound to this test's isolated database."""
    return _shared_factory(db_engine)


@pytest.fixture(autouse=True)
def _release_closed_event_loops():
    """Remove closed loops retained by anyio's private per-run registry.

    Anyio versions without this implementation detail simply skip cleanup.
    """
    yield
    try:
        from anyio.lowlevel import _run_vars
    except Exception:
        return
    for loop in list(_run_vars):
        if getattr(loop, "is_closed", lambda: False)():
            _run_vars.pop(loop, None)


@pytest.fixture
def db_session(TestSession):
    """Isolated session backed by the per-test in-memory engine."""
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seed_accounts(db_session):
    """Seed the standard chart of accounts; returns dict keyed by account_number."""
    from app.models.accounts import Account, AccountType

    accounts_by_number = {}
    for data in CHART_OF_ACCOUNTS:
        acct = Account(
            account_number=data["account_number"],
            name=data["name"],
            account_type=AccountType(data["account_type"]),
            bank_kind=data.get("bank_kind"),
            is_system=True,
            balance=Decimal("0"),
        )
        db_session.add(acct)
        accounts_by_number[data["account_number"]] = acct
    db_session.commit()
    return accounts_by_number


@pytest.fixture
def seed_customer(db_session):
    """Seed a single active Customer and return it."""
    from app.models.contacts import Customer

    customer = Customer(name="Test Customer", is_active=True)
    db_session.add(customer)
    db_session.commit()
    return customer


# ---------------------------------------------------------------------------
# Client fixtures — both wire get_db to the per-test in-memory engine
# ---------------------------------------------------------------------------


def _wire_app(TestSession):
    """Override app's get_db dependency to use the per-test session factory."""

    def override_get_db(request: HTTPConnection = None):
        session = TestSession()
        # Mirror production's attribution stamping so tests exercise the
        # session.info path (the mechanism that works on frozen Windows),
        # not just the contextvar fallback.
        http_session = getattr(request, "session", None) if request else None
        if isinstance(http_session, dict) and http_session.get("authenticated") is True:
            session.info["acting_username"] = http_session.get("username") or "operator"
        elif request is not None:
            tp = getattr(getattr(request, "state", None), "token_principal", None)
            if isinstance(tp, dict) and tp.get("username"):
                session.info["acting_username"] = tp["username"]
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def unauthed_client(db_engine, TestSession):
    """Unauthenticated TestClient backed by the per-test in-memory DB.

    Use this fixture in tests that exercise the auth flow itself (setup, login,
    logout) where you need to start from an unauthenticated state.
    """
    _wire_app(TestSession)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client(db_engine, TestSession):
    """Authenticated TestClient backed by the per-test in-memory DB.

    Auth setup is performed during fixture setup so every API call
    made through this client is already authenticated.
    """
    _wire_app(TestSession)
    with TestClient(app) as c:
        r = c.post("/api/auth/setup", json={"password": "test-password-123"})
        assert r.status_code == 200, f"Auth setup failed: {r.text}"
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def authed_client(client):
    """Alias for client (already authenticated). Kept for backwards compatibility."""
    return client


@pytest.fixture
def db():
    """Legacy fixture: fresh session against the module-level engine.

    Tests that import this fixture directly (not via client) get a session
    backed by whatever engine db_module.SessionLocal points at.
    """
    session = db_module.SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
