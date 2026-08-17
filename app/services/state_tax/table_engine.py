# ============================================================================
# Table-driven state payroll engine.
# ----------------------------------------------------------------------------
# Most states withhold income tax the same way: annualize the period's taxable
# wages, subtract a standard deduction and/or exemption allowance, run the
# result through a progressive bracket schedule (or a single flat rate), then
# divide back down to the pay period. The differences between states are
# DATA — bracket edges, rates, deduction amounts, SUTA wage bases, and any
# state-specific disability / paid-leave premiums.
#
# So rather than hand-coding forty-odd near-identical engine classes, this
# module implements that shared shape once and reads the per-state numbers
# from reviewable JSON files in ``tables/``. A state whose rules do NOT fit
# the shape (Washington's per-hour L&I, Oregon's transit taxes) still gets a
# dedicated engine class; the registry in ``__init__`` prefers those.
#
# WHY DATA FILES AND NOT CONSTANTS
# --------------------------------
# Payroll tax figures change every year, and a wrong figure buried in Python
# is invisible. Each table carries its own provenance — ``tax_year``,
# ``source`` (the state's published withholding guide), and a ``verified``
# flag an operator sets only after checking the numbers against that source.
# ``python -m app.services.state_tax.table_engine`` prints the coverage and
# verification status of every table so the unchecked ones stay visible.
#
# STRICT MODE
# -----------
# With PAYROLL_STRICT_TAX_TABLES=1 an unverified table withholds NO state
# income tax and says so on the pay stub, rather than withholding an amount
# nobody has signed off on. The default is permissive — matching how the
# existing hand-written CA / NY / OR engines already behave — because a
# close-but-unconfirmed withholding is generally nearer the truth than zero.
# Operators running real payroll should verify their states and flip the
# flags; the report above tells them what is left to check.
#
# DISCLAIMER: Every figure in ``tables/`` is an approximation until its
# ``verified`` flag is set. Verify against the state's current withholding
# guide before relying on any of it for actual tax filing.
# ============================================================================

from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

from app.services.state_tax.base import StateEngine, StateTaxResult

CENT = Decimal("0.01")

TABLE_DIR = Path(__file__).parent / "tables"

# Filing statuses the engine understands, mirroring FilingStatus on Employee.
_FILING_STATUSES = ("single", "married", "head_of_household")

# Fallback SUTA wage base for a table that omits one — matches the base class.
_DEFAULT_SUTA_WAGE_BASE = Decimal("9000")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(value, default="0") -> Decimal:
    """Coerce a JSON scalar to Decimal. Strings keep exact decimal precision."""
    if value is None:
        value = default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _capped_wages(gross: Decimal, ytd_gross: Decimal, wage_base: Decimal) -> Decimal:
    """Portion of `gross` still below an annual wage-base cap."""
    if wage_base is None:
        return gross
    if ytd_gross >= wage_base:
        return Decimal("0")
    if ytd_gross + gross > wage_base:
        return wage_base - ytd_gross
    return gross


def _tax_from_brackets(wage: Decimal, brackets) -> Decimal:
    """Progressive tax on `wage` given ascending (lower_bound, rate) pairs.

    Same derivation the federal and CA engines use: accumulate each bracket's
    marginal slice rather than transcribing cumulative "tax on the excess
    over" figures, so a table cannot disagree with itself.
    """
    if wage <= 0:
        return Decimal("0")
    tax = Decimal("0")
    for i, (lower, rate) in enumerate(brackets):
        if wage <= lower:
            break
        upper = brackets[i + 1][0] if i + 1 < len(brackets) else None
        top = wage if upper is None else min(wage, upper)
        tax += (top - lower) * rate
        if upper is None or wage <= upper:
            break
    return tax


class StateTaxTableError(ValueError):
    """Raised when a table file is malformed — surfaced at load, not at payroll."""


def _parse_brackets(raw, state: str) -> dict:
    """Normalize the per-filing-status bracket map into Decimal pairs."""
    parsed: dict[str, list] = {}
    for status, rows in (raw or {}).items():
        pairs = []
        previous = None
        for row in rows:
            if len(row) != 2:
                raise StateTaxTableError(
                    f"{state}: bracket rows must be [lower_bound, rate], got {row!r}"
                )
            lower, rate = _dec(row[0]), _dec(row[1])
            if previous is not None and lower <= previous:
                raise StateTaxTableError(
                    f"{state}: bracket lower bounds must ascend "
                    f"({lower} follows {previous})"
                )
            previous = lower
            pairs.append((lower, rate))
        if pairs and pairs[0][0] != 0:
            raise StateTaxTableError(
                f"{state}: first bracket must start at 0, got {pairs[0][0]}"
            )
        parsed[status] = pairs
    return parsed


def _parse_other_items(raw, state: str, side: str) -> list:
    """Normalize a list of {label, rate, wage_base} premium definitions."""
    items = []
    for entry in raw or []:
        label = entry.get("label")
        if not label:
            raise StateTaxTableError(f"{state}: {side} item is missing a label")
        wage_base = entry.get("wage_base")
        items.append(
            {
                "label": label,
                "rate": _dec(entry.get("rate")),
                "wage_base": None if wage_base is None else _dec(wage_base),
            }
        )
    return items


class TableDrivenStateEngine(StateEngine):
    """A StateEngine whose numbers come from a validated table dict.

    Construct via :func:`load_table` / :func:`build_engine` rather than
    directly, so the table is validated once at import instead of during a
    pay run.
    """

    def __init__(self, table: dict) -> None:
        state = str(table.get("state") or "??").strip().upper()
        if len(state) != 2:
            raise StateTaxTableError(f"state must be a 2-letter code, got {state!r}")

        self.state_code = state
        self.name = table.get("name") or state
        self.tax_year = table.get("tax_year")
        self.verified = bool(table.get("verified", False))
        self.source = table.get("source") or ""
        self.notes = table.get("notes") or ""

        income = table.get("income_tax") or {}
        self.method = (income.get("method") or "none").strip().lower()
        if self.method not in ("none", "flat", "brackets"):
            raise StateTaxTableError(
                f"{state}: income_tax.method must be none/flat/brackets, "
                f"got {self.method!r}"
            )
        self.flat_rate = _dec(income.get("rate"))
        self.brackets = _parse_brackets(income.get("brackets"), state)
        self.standard_deduction = {
            status: _dec((income.get("standard_deduction") or {}).get(status))
            for status in _FILING_STATUSES
        }
        self.exemption_allowance = {
            status: _dec((income.get("exemption_allowance") or {}).get(status))
            for status in _FILING_STATUSES
        }
        supplemental = income.get("supplemental_rate")
        self.supplemental_rate = None if supplemental is None else _dec(supplemental)

        if self.method == "brackets" and not self.brackets:
            raise StateTaxTableError(f"{state}: method 'brackets' but none defined")

        suta = table.get("suta") or {}
        self.suta_wage_base = _dec(suta.get("wage_base"), _DEFAULT_SUTA_WAGE_BASE)
        # New-employer rate, used when the operator has not entered the
        # experience rate the state assigned them. Always a fallback, never
        # preferred over a configured rate.
        self.suta_default_rate = _dec(suta.get("default_rate"))

        self.employee_other = _parse_other_items(
            table.get("employee_other"), state, "employee_other"
        )
        self.employer_other = _parse_other_items(
            table.get("employer_other"), state, "employer_other"
        )

    # -- income tax ---------------------------------------------------------

    def _annual_income_tax(self, annual_taxable: Decimal, fs: str) -> Decimal:
        """State income tax on an annualized taxable-wage figure."""
        base = annual_taxable
        base -= self.standard_deduction.get(fs, Decimal("0"))
        base -= self.exemption_allowance.get(fs, Decimal("0"))
        if base <= 0:
            return Decimal("0")

        if self.method == "flat":
            return base * self.flat_rate

        schedule = self.brackets.get(fs) or self.brackets.get("single")
        if not schedule:
            return Decimal("0")
        return _tax_from_brackets(base, schedule)

    def calculate(
        self,
        *,
        gross: Decimal,
        taxable: Decimal,
        ytd_gross: Decimal,
        pay_periods: int,
        hours: Decimal,
        filing_status: str,
        wc_class_code: str | None,
    ) -> StateTaxResult:
        if gross <= 0 or taxable <= 0:
            return StateTaxResult()

        fs = filing_status if filing_status in _FILING_STATUSES else "single"
        detail: dict[str, Decimal] = {}

        # --- income tax ---
        income_tax = Decimal("0.00")
        if self.method == "none":
            pass
        elif strict_mode() and not self.verified:
            # Withhold nothing rather than an unreviewed amount, and say so on
            # the stub so the omission is visible instead of looking like a
            # no-income-tax state.
            detail[f"{self.state_code} income tax (unverified table — not applied)"] = (
                Decimal("0.00")
            )
        else:
            annual = taxable * pay_periods
            income_tax = _q(self._annual_income_tax(annual, fs) / pay_periods)
            if income_tax > 0:
                label = f"{self.state_code} income tax"
                if not self.verified:
                    label += " (unverified)"
                detail[label] = income_tax

        # --- state disability / paid-leave premiums ---
        employee_other = Decimal("0.00")
        for item in self.employee_other:
            wages = _capped_wages(gross, ytd_gross, item["wage_base"])
            amount = _q(wages * item["rate"])
            if amount:
                employee_other += amount
                detail[item["label"]] = amount

        employer_other = Decimal("0.00")
        for item in self.employer_other:
            wages = _capped_wages(gross, ytd_gross, item["wage_base"])
            amount = _q(wages * item["rate"])
            if amount:
                employer_other += amount
                detail[item["label"]] = amount

        return StateTaxResult(
            income_tax=income_tax,
            employee_other=employee_other,
            employer_other=employer_other,
            detail=detail,
        )


# --- loading ----------------------------------------------------------------


def strict_mode() -> bool:
    """True when unverified tables should withhold nothing.

    Read at call time rather than import time so tests and operators can flip
    the environment variable without re-importing the package.
    """
    from app.config import PAYROLL_STRICT_TAX_TABLES

    return bool(PAYROLL_STRICT_TAX_TABLES)


def load_table(path: Path) -> dict:
    """Read and JSON-parse one table file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise StateTaxTableError(f"{path.name}: invalid JSON — {exc}") from exc


@lru_cache(maxsize=1)
def load_all_engines() -> dict:
    """Build every table-driven engine, keyed by uppercase state code.

    Cached: tables are static data read once per process. Malformed files
    raise StateTaxTableError at first use so a bad table fails loudly during
    startup or tests rather than silently mis-withholding in a pay run.
    """
    engines: dict[str, TableDrivenStateEngine] = {}
    if not TABLE_DIR.is_dir():
        return engines
    for path in sorted(TABLE_DIR.glob("*.json")):
        table = load_table(path)
        engine = TableDrivenStateEngine(table)
        stem = path.stem.upper()
        if engine.state_code != stem:
            raise StateTaxTableError(
                f"{path.name}: filename says {stem} but table says {engine.state_code}"
            )
        engines[engine.state_code] = engine
    return engines


def coverage_report() -> list:
    """Per-state summary of what is on file and whether anyone checked it."""
    rows = []
    for code, engine in sorted(load_all_engines().items()):
        rows.append(
            {
                "state": code,
                "name": engine.name,
                "tax_year": engine.tax_year,
                "method": engine.method,
                "verified": engine.verified,
                "source": engine.source,
                "suta_wage_base": engine.suta_wage_base,
                "suta_default_rate": engine.suta_default_rate,
                "other_items": len(engine.employee_other) + len(engine.employer_other),
            }
        )
    return rows


if __name__ == "__main__":  # pragma: no cover - operator convenience
    rows = coverage_report()
    verified = sum(1 for r in rows if r["verified"])
    print(
        f"{len(rows)} state tax tables — {verified} verified, "
        f"{len(rows) - verified} awaiting review\n"
    )
    print(f"{'ST':<4}{'METHOD':<10}{'YEAR':<7}{'SUTA BASE':>12}  {'OK':<4}NAME")
    for row in rows:
        flag = "yes" if row["verified"] else "--"
        print(
            f"{row['state']:<4}{row['method']:<10}{row['tax_year']!s:<7}"
            f"{row['suta_wage_base']:>12}  {flag:<4}{row['name']}"
        )
