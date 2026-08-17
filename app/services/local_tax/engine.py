# ============================================================================
# Local / municipal payroll tax engine.
# ----------------------------------------------------------------------------
# The layer below the states: Pennsylvania EIT + LST, Ohio municipal and
# school-district taxes, NYC and Yonkers, Maryland and Indiana county taxes,
# Kentucky occupational license fees, Michigan city income taxes. Same design
# as the state tables (see state_tax/table_engine.py): one engine, reviewable
# JSON data under ``localities/``, per-file provenance with a ``verified``
# flag, and validation at load time rather than mid-pay-run.
#
# An employee carries two locality codes — ``work_locality`` and
# ``residence_locality`` — each pointing at a rule. What a rule collects and
# *where it attaches* is its ``basis``:
#
#   work              Attaches to the work locality. Nonresidents pay
#                     ``nonresident_rate`` (falling back to ``resident_rate``
#                     if none is published); an employee who also lives there
#                     pays ``resident_rate``. OH municipal, KY occupational,
#                     Philadelphia wage tax.
#
#   residence         Attaches to the residence locality regardless of where
#                     the work happens. MD counties, IN counties, OH school
#                     districts, NYC.
#
#   higher_of         Pennsylvania Act 32: the employer withholds the HIGHER
#                     of the work locality's nonresident rate and the
#                     residence locality's resident rate, remitted to the
#                     work-place collector. Applied at the work locality.
#
#   work_or_residence Michigan cities: the work city collects (resident or
#                     nonresident rate), and an employee living in a
#                     different taxing city also owes their residence city
#                     the resident rate LESS a credit for what the work city
#                     took. The credit here is the full work-city amount,
#                     floored at zero — Michigan's actual credit is capped at
#                     what the residence city would charge on the same wages
#                     at its nonresident rate; the simplification
#                     over-credits slightly and therefore under-withholds a
#                     few dollars rather than over-withholding. Documented
#                     in docs/local-taxes.md.
#
# Amount kinds, orthogonal to basis:
#
#   percent               rate × period taxable wages (the default)
#   brackets              progressive annualized schedule (NYC)
#   percent_of_state_tax  rate × the state income tax withheld this period
#                         (the Yonkers resident surcharge)
#
# A rule may also carry ``lst_per_year`` — Pennsylvania's Local Services
# Tax, a flat annual amount collected in level per-period installments at
# the work locality — and ``employer_rate`` / ``employer_flat_per_year``
# for employer-side levies (e.g. occupational privilege head taxes).
#
# DISCLAIMER: Every figure in ``localities/`` is an approximation until its
# file's ``verified`` flag is set. Local rates change more often than state
# ones — PA EIT rates are per-municipality-pair, OH school districts vote on
# levies — so verify against the collector's published rate before filing.
# ============================================================================

from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

from app.services.local_tax.base import LocalTaxResult

CENT = Decimal("0.01")

LOCALITY_DIR = Path(__file__).parent / "localities"

_KINDS = ("percent", "brackets", "percent_of_state_tax")
_BASES = ("work", "residence", "higher_of", "work_or_residence")

_FILING_STATUSES = ("single", "married", "head_of_household")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(value, default="0") -> Decimal:
    if value is None:
        value = default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _tax_from_brackets(wage: Decimal, brackets) -> Decimal:
    """Progressive tax on `wage` — same marginal-slice derivation as the
    state and federal engines, so a schedule cannot disagree with itself."""
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


class LocalTaxTableError(ValueError):
    """Raised for a malformed locality file — at load, never during payroll."""


class LocalityRule:
    """One locality's validated tax rule."""

    def __init__(self, raw: dict, source_file: str) -> None:
        code = str(raw.get("code") or "").strip().upper()
        if not code:
            raise LocalTaxTableError(f"{source_file}: locality entry has no code")
        self.code = code
        self.name = raw.get("name") or code
        self.state = str(raw.get("state") or "").strip().upper()

        self.kind = (raw.get("kind") or "percent").strip().lower()
        if self.kind not in _KINDS:
            raise LocalTaxTableError(
                f"{code}: kind must be one of {_KINDS}, got {self.kind!r}"
            )
        self.basis = (raw.get("basis") or "work").strip().lower()
        if self.basis not in _BASES:
            raise LocalTaxTableError(
                f"{code}: basis must be one of {_BASES}, got {self.basis!r}"
            )

        self.resident_rate = _dec(raw.get("resident_rate"))
        self.nonresident_rate = (
            _dec(raw["nonresident_rate"])
            if raw.get("nonresident_rate") is not None
            else None
        )

        self.brackets: dict[str, list] = {}
        for status, rows in (raw.get("brackets") or {}).items():
            pairs = []
            previous = None
            for row in rows:
                if len(row) != 2:
                    raise LocalTaxTableError(
                        f"{code}: bracket rows must be [lower_bound, rate]"
                    )
                lower, rate = _dec(row[0]), _dec(row[1])
                if previous is not None and lower <= previous:
                    raise LocalTaxTableError(f"{code}: bracket bounds must ascend")
                previous = lower
                pairs.append((lower, rate))
            if pairs and pairs[0][0] != 0:
                raise LocalTaxTableError(f"{code}: first bracket must start at 0")
            self.brackets[status] = pairs
        if self.kind == "brackets" and not self.brackets:
            raise LocalTaxTableError(f"{code}: kind 'brackets' but none defined")

        self.lst_per_year = _dec(raw.get("lst_per_year"))
        self.employer_rate = _dec(raw.get("employer_rate"))
        self.employer_flat_per_year = _dec(raw.get("employer_flat_per_year"))

    # -- amount helpers ------------------------------------------------------

    def _bracket_tax(
        self, taxable: Decimal, pay_periods: int, filing_status: str
    ) -> Decimal:
        fs = filing_status if filing_status in self.brackets else "single"
        schedule = self.brackets.get(fs) or self.brackets.get("single")
        if not schedule:
            return Decimal("0")
        annual = _tax_from_brackets(taxable * pay_periods, schedule)
        return annual / pay_periods

    def amount(
        self,
        *,
        rate: Decimal,
        taxable: Decimal,
        pay_periods: int,
        filing_status: str,
        state_income_tax: Decimal,
    ) -> Decimal:
        """The employee-side tax for one period at the given rate."""
        if self.kind == "brackets":
            return _q(self._bracket_tax(taxable, pay_periods, filing_status))
        if self.kind == "percent_of_state_tax":
            return _q(state_income_tax * rate)
        return _q(taxable * rate)


class LocalityFileMeta:
    """Provenance for one localities/*.json file."""

    def __init__(self, raw: dict, filename: str) -> None:
        self.filename = filename
        self.state = str(raw.get("state") or "").strip().upper()
        self.tax_year = raw.get("tax_year")
        self.verified = bool(raw.get("verified", False))
        self.source = raw.get("source") or ""
        self.notes = raw.get("notes") or ""


@lru_cache(maxsize=1)
def _load() -> tuple:
    """Parse every localities file → ({code: rule}, [file metas])."""
    rules: dict[str, LocalityRule] = {}
    metas: list[LocalityFileMeta] = []
    if not LOCALITY_DIR.is_dir():
        return rules, metas
    for path in sorted(LOCALITY_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise LocalTaxTableError(f"{path.name}: invalid JSON — {exc}") from exc
        meta = LocalityFileMeta(raw, path.name)
        metas.append(meta)
        for entry in raw.get("localities") or []:
            rule = LocalityRule(entry, path.name)
            if rule.code in rules:
                raise LocalTaxTableError(
                    f"{path.name}: duplicate locality code {rule.code}"
                )
            rule.verified = meta.verified
            rules[rule.code] = rule
    return rules, metas


def get_locality(code: str | None) -> LocalityRule | None:
    if not code:
        return None
    return _load()[0].get(code.strip().upper())


def supported_localities() -> list:
    return sorted(_load()[0])


def coverage_report() -> list:
    rows = []
    rules, metas = _load()
    by_state: dict[str, int] = {}
    for rule in rules.values():
        by_state[rule.state] = by_state.get(rule.state, 0) + 1
    for meta in metas:
        rows.append(
            {
                "file": meta.filename,
                "state": meta.state,
                "tax_year": meta.tax_year,
                "verified": meta.verified,
                "source": meta.source,
                "localities": by_state.get(meta.state, 0),
            }
        )
    return rows


# --- the calculation --------------------------------------------------------


def _label(rule: LocalityRule, suffix: str = "") -> str:
    text = f"{rule.name} local tax"
    if suffix:
        text = f"{rule.name} {suffix}"
    if not getattr(rule, "verified", False):
        text += " (unverified)"
    return text


def calculate_local_taxes(
    *,
    work_locality: str | None,
    residence_locality: str | None,
    taxable: Decimal,
    pay_periods: int,
    filing_status: str = "single",
    state_income_tax: Decimal = Decimal("0"),
) -> LocalTaxResult:
    """Local tax for one pay period given the employee's two locality codes.

    ``taxable`` is the period's income-tax wage base (gross less pre-tax
    deductions) — local wage taxes almost universally piggyback on it.
    Unknown codes are collected in ``result.unknown`` rather than raised:
    payroll must not 500 over a typo, but the route and the tests can see
    the miss instead of a silent $0.
    """
    result = LocalTaxResult()
    if taxable <= 0:
        return result

    work = get_locality(work_locality)
    residence = get_locality(residence_locality)
    if work_locality and work is None:
        result.unknown.append(work_locality.strip().upper())
    if residence_locality and residence is None:
        result.unknown.append(residence_locality.strip().upper())

    # An employee is a resident of the work locality only when the operator
    # SAYS so by setting residence_locality to the same code. A missing
    # residence withholds at the nonresident rate — residency claims need
    # affirmative configuration, not a guess.
    same = work is not None and residence is not None and work.code == residence.code

    common = dict(
        taxable=taxable,
        pay_periods=pay_periods,
        filing_status=filing_status,
        state_income_tax=state_income_tax,
    )

    work_city_withheld = Decimal("0")

    # --- taxes attaching to the WORK locality ---
    if work is not None and work.basis in ("work", "higher_of", "work_or_residence"):
        if same:
            rate = work.resident_rate
        elif work.basis == "higher_of":
            # PA Act 32: higher of work nonresident vs residence resident.
            work_rate = (
                work.nonresident_rate
                if work.nonresident_rate is not None
                else work.resident_rate
            )
            res_rate = (
                residence.resident_rate
                if residence is not None and residence.basis == "higher_of"
                else Decimal("0")
            )
            rate = max(work_rate, res_rate)
        else:
            rate = (
                work.nonresident_rate
                if work.nonresident_rate is not None
                else work.resident_rate
            )
        amount = work.amount(rate=rate, **common)
        if amount:
            work_city_withheld = amount
            result.employee += amount
            result.detail[_label(work)] = amount
    elif work is not None and work.basis == "residence" and not same:
        # A residence-basis locality can still tax nonresidents who WORK
        # there on their wages — Yonkers' nonresident earnings tax. The
        # resident side may be a state-tax surcharge (percent_of_state_tax),
        # so the nonresident side is always a plain wage rate.
        if work.nonresident_rate is not None:
            amount = _q(taxable * work.nonresident_rate)
            if amount:
                result.employee += amount
                result.detail[_label(work, "(nonresident)")] = amount

    # PA Local Services Tax — flat per year, level per-period installments,
    # collected by the WORK locality regardless of basis or residence.
    if work is not None and work.lst_per_year > 0:
        lst = _q(work.lst_per_year / pay_periods)
        if lst:
            result.employee += lst
            result.detail[_label(work, "LST")] = lst

    # --- taxes attaching to the RESIDENCE locality ---
    if residence is not None and not same:
        if residence.basis == "residence":
            amount = residence.amount(rate=residence.resident_rate, **common)
            if amount:
                result.employee += amount
                result.detail[_label(residence)] = amount
        elif residence.basis == "work_or_residence":
            # Michigan: residence city at the resident rate, credited for the
            # work-city withholding (see the simplification note up top).
            amount = residence.amount(rate=residence.resident_rate, **common)
            amount = max(Decimal("0"), amount - work_city_withheld)
            amount = _q(amount)
            if amount:
                result.employee += amount
                result.detail[_label(residence, "(residence)")] = amount
    elif residence is not None and same and residence.basis == "residence":
        # Working where you live in a residence-basis locality (MD county,
        # NYC, OH school district): the residence tax still applies.
        amount = residence.amount(rate=residence.resident_rate, **common)
        if amount:
            result.employee += amount
            result.detail[_label(residence)] = amount

    # --- employer-side levies (attach to the work locality) ---
    if work is not None:
        if work.employer_rate > 0:
            amount = _q(taxable * work.employer_rate)
            if amount:
                result.employer += amount
                result.detail[_label(work, "(employer)")] = amount
        if work.employer_flat_per_year > 0:
            amount = _q(work.employer_flat_per_year / pay_periods)
            if amount:
                result.employer += amount
                result.detail[_label(work, "(employer, flat)")] = amount

    result.employee = _q(result.employee)
    result.employer = _q(result.employer)
    return result


if __name__ == "__main__":  # pragma: no cover - operator convenience
    rows = coverage_report()
    total = sum(r["localities"] for r in rows)
    verified = sum(1 for r in rows if r["verified"])
    print(
        f"{len(rows)} locality files, {total} localities — "
        f"{verified} files verified, {len(rows) - verified} awaiting review\n"
    )
    print(f"{'FILE':<12}{'ST':<4}{'YEAR':<7}{'RULES':>6}  {'OK':<4}SOURCE")
    for row in rows:
        flag = "yes" if row["verified"] else "--"
        print(
            f"{row['file']:<12}{row['state']:<4}{row['tax_year']!s:<7}"
            f"{row['localities']:>6}  {flag:<4}{row['source']}"
        )
