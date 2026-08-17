# ============================================================================
# Local Tax — result type shared by the locality engine.
# ----------------------------------------------------------------------------
# Mirrors StateTaxResult one level down: employee- and employer-side local
# tax with an itemized detail map for pay-stub rendering, plus the list of
# locality codes that matched nothing so a typo is visible instead of a
# silent $0.
# ============================================================================

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class LocalTaxResult:
    employee: Decimal = Decimal("0")  # total employee-side local tax withheld
    employer: Decimal = Decimal("0")  # total employer-side local payroll tax
    detail: dict = field(default_factory=dict)  # {human_label: Decimal}
    unknown: list = field(default_factory=list)  # locality codes with no rule
