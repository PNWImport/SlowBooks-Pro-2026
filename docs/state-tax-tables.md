# State tax tables

The current implementation is `TableEngine`, driven by `StateSpec` entries in
`app/services/state_tax/tables.py`. Washington, California, New York, and Oregon
have dedicated engines. See [state withholding](state-withholding.md) for the
catalog, formulas, sources, and known simplifications.

The former JSON-table instructions and state `PAYROLL_STRICT_TAX_TABLES` switch
do not describe the current implementation. Do not rely on that variable to
block unverified state calculations. Local-tax JSON has separate verification
metadata; see [local taxes](local-taxes.md).

## Verification before payroll

The source records a prior 2026-09-03 verification claim. The 2026-09-07 debug
pass did not independently reverify every rate, bracket, wage base, or formula.
For each jurisdiction used, compare its official current-year withholding guide
with the engine, employee inputs, employer-specific rates, and representative
paychecks. A rate match alone is not a complete payroll verification.

One limited spot-check matched Illinois's 4.95% rate and $2,925 Line 1 annual
allowance to the [official 2026 IL-700-T](https://tax.illinois.gov/forms/withholding/currentyear/il-700-t-withholding-guide-tables.html).
That guide also distinguishes Line 2 allowances; the current single allowance
field does not model that distinction. Illinois is therefore not marked fully
verified by this pass.

The Connecticut paid-leave cap was corrected from $176,100 to $184,500 after
checking [CT's contribution rule](https://www.ctpaidleave.org/how-ct-paid-leave-works/contributions)
and [SSA's 2026 cap](https://www.ssa.gov/OACT/cola/cbbdet.html). Boundary tests cover
wages below, crossing, and at the cap. This does not verify all Connecticut taxes.

Minnesota's cap was corrected to $185,000, including its rounding rule, using
[DEED's 2026 guidance](https://mn.gov/deed/assets/paid-leave-small-employer-premium-rate-designation-acc_tcm1045-716947.pdf).
Tests cover both employee and employer amounts at the boundary. Small-employer
eligibility and reduced employer premiums remain outside this correction.

**Open release check:** `SS_BASE=176100` still feeds CO/MA/DE paid-leave items.
Review each program's current cap, rounding, rates, and exemptions before payroll;
do not assume one updated federal constant verifies every state's rules.
