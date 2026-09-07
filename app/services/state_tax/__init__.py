# ============================================================================
# State Tax package — per-state payroll withholding engine registry.
# ----------------------------------------------------------------------------
# get_engine() resolves a 2-letter state code (case-insensitive) to a concrete
# StateEngine. Dedicated engines exist for WA, CA, NY, and OR; every other
# state and DC is a TableEngine driven by tables.py. An unknown code (a typo,
# a territory) falls back to a zero-rate GenericStateEngine so it contributes
# no state income tax rather than a wrong guess.
#
# Engines are stateless, so the registry holds module-level singletons.
# ============================================================================

from app.services.state_tax.base import StateEngine, StateTaxResult
from app.services.state_tax.ca import CAEngine
from app.services.state_tax.generic import GenericStateEngine
from app.services.state_tax.ny import NYEngine
from app.services.state_tax.oregon import OregonEngine
from app.services.state_tax.table_engine import TableEngine, describe
from app.services.state_tax.tables import DEDICATED, STATES
from app.services.state_tax.wa import WAEngine

__all__ = [
    "StateEngine",
    "StateTaxResult",
    "GenericStateEngine",
    "WAEngine",
    "CAEngine",
    "NYEngine",
    "OregonEngine",
    "TableEngine",
    "get_engine",
    "list_states",
    "is_supported",
]

# Registry of dedicated engines, keyed by uppercase 2-letter state code.
_REGISTRY: dict[str, StateEngine] = {
    "WA": WAEngine(),
    "CA": CAEngine(),
    "NY": NYEngine(),
    "OR": OregonEngine(),
}
for _code, _spec in STATES.items():
    _REGISTRY.setdefault(_code, TableEngine(_spec))

# Shared fallback for any state without a dedicated engine (flat_rate 0).
_GENERIC = GenericStateEngine()


def get_engine(state_code: str | None) -> StateEngine:
    """Return the payroll engine for a 2-letter state code (case-insensitive).

    Unknown or missing codes return a zero-rate GenericStateEngine.
    """
    if not state_code:
        return _GENERIC
    return _REGISTRY.get(state_code.strip().upper(), _GENERIC)


def is_supported(state_code: str | None) -> bool:
    return bool(state_code) and state_code.strip().upper() in _REGISTRY


def list_states() -> list[dict]:
    """Catalog of every supported jurisdiction: method, summary, deductions,
    other items, SUTA base, the publication the figures came from."""
    out = []
    for code in sorted(_REGISTRY):
        if code in STATES:
            out.append(describe(STATES[code]))
        else:
            name, base, summary = DEDICATED[code]
            out.append(
                {
                    "code": code,
                    "name": name,
                    "method": "dedicated",
                    "summary": summary,
                    "suta_wage_base": float(base),
                    "uses_local_rate": False,
                    "uses_rate_election": False,
                    "year": "2026-approximate",
                    "source": f"app/services/state_tax/{code.lower() if code != 'OR' else 'oregon'}.py",
                    "notes": "",
                }
            )
    return out


def suta_rate_for(
    state_code: str | None, configured: dict | None = None, tables: bool = True
):
    """Resolve the employer SUTA rate for a state.

    A rate in `configured` always wins. Failing that, returns the state's
    published new-employer rate from the engine registry (a reasonable
    stand-in for a state the operator has not set up).
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

    engine = _REGISTRY.get(code)
    if engine is None:
        return None
    # None = the state ships no published rate (the dedicated WA/CA/NY/OR
    # engines, for one), which is distinct from a published rate of zero.
    published = getattr(engine, "suta_default_rate", None)
    if published is not None and published > 0:
        return published
    return None
