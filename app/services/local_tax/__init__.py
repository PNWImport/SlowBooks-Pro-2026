# ============================================================================
# Local Tax package — municipal / county / school-district payroll taxes.
# ----------------------------------------------------------------------------
# The layer below the state engines. See engine.py for the basis semantics
# (work / residence / higher_of / work_or_residence) and localities/ for the
# reviewable per-state data files.
# ============================================================================

from app.services.local_tax.base import LocalTaxResult
from app.services.local_tax.engine import (
    LocalityRule,
    LocalTaxTableError,
    calculate_local_taxes,
    coverage_report,
    get_locality,
    supported_localities,
)

__all__ = [
    "LocalTaxResult",
    "LocalityRule",
    "LocalTaxTableError",
    "calculate_local_taxes",
    "coverage_report",
    "get_locality",
    "supported_localities",
]
