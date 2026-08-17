# ============================================================================
# State Tax package — per-state payroll withholding engine registry.
# ----------------------------------------------------------------------------
# get_engine() resolves a 2-letter state code (case-insensitive) to a concrete
# StateEngine, checking three sources in order:
#
#   1. Dedicated engine classes — WA, CA, NY, OR. These states have rules the
#      generic table shape cannot express (WA's per-hour L&I assessment,
#      Oregon's transit taxes), so they stay hand-written.
#   2. Table-driven engines — every other state plus DC, built from the
#      reviewable JSON in ``tables/``. See table_engine.py for the schema and
#      the verified-flag policy.
#   3. A zero-rate GenericStateEngine, so a code that matches nothing (a typo,
#      a territory) contributes no state income tax rather than a wrong guess.
#
# Engines are stateless, so the registry holds module-level singletons.
# ============================================================================

from app.services.state_tax.base import StateEngine, StateTaxResult
from app.services.state_tax.ca import CAEngine
from app.services.state_tax.generic import GenericStateEngine
from app.services.state_tax.ny import NYEngine
from app.services.state_tax.oregon import OregonEngine
from app.services.state_tax.table_engine import (
    StateTaxTableError,
    TableDrivenStateEngine,
    coverage_report,
    load_all_engines,
)
from app.services.state_tax.wa import WAEngine

__all__ = [
    "StateEngine",
    "StateTaxResult",
    "GenericStateEngine",
    "TableDrivenStateEngine",
    "StateTaxTableError",
    "WAEngine",
    "CAEngine",
    "NYEngine",
    "OregonEngine",
    "get_engine",
    "supported_states",
    "coverage_report",
    "suta_rate_for",
]

# Hand-written engines. These take precedence over any table of the same name.
_DEDICATED: dict[str, StateEngine] = {
    "WA": WAEngine(),
    "CA": CAEngine(),
    "NY": NYEngine(),
    "OR": OregonEngine(),
}

# Shared fallback for a code that matches nothing at all (flat_rate 0).
_GENERIC = GenericStateEngine()


def get_engine(state_code: str | None) -> StateEngine:
    """Return the payroll engine for a 2-letter state code (case-insensitive).

    Unknown or missing codes return a zero-rate GenericStateEngine.
    """
    if not state_code:
        return _GENERIC
    code = state_code.strip().upper()
    engine = _DEDICATED.get(code)
    if engine is not None:
        return engine
    return load_all_engines().get(code, _GENERIC)


def supported_states() -> list:
    """Every state code with a real engine behind it, dedicated or table-driven."""
    return sorted(set(_DEDICATED) | set(load_all_engines()))


def suta_rate_for(
    state_code: str | None, configured: dict | None = None, tables: bool = True
):
    """Resolve the employer SUTA rate for a state.

    States assign each employer an *experience rate* that no library can know,
    so a rate in `configured` always wins. Failing that, and only when
    `tables` is true, this returns the state's published new-employer rate —
    a reasonable stand-in for a state the operator has not set up, and far
    better than applying one state's rate to every state, which is what the
    old global constant did.

    Pass ``tables=False`` to ask only "has the operator configured this
    state?", which lets a caller slot its own default in between the two
    sources. Returns None when nothing is known.
    """
    from decimal import Decimal

    if not state_code:
        return None
    code = state_code.strip().upper()

    if configured:
        for key, value in configured.items():
            if str(key).strip().upper() == code and value is not None:
                return Decimal(str(value))

    if not tables:
        return None

    engine = load_all_engines().get(code)
    if engine is not None and engine.suta_default_rate > 0:
        return engine.suta_default_rate
    return None
