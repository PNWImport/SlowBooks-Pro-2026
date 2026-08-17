# State Tax Tables

How per-state payroll withholding is configured, and — more importantly —
how to verify it before you run real payroll.

## Why tables instead of code

Before this, four states had hand-written engines (WA, CA, NY, OR) and the
other forty-six fell through to `GenericStateEngine(flat_rate=0)`. An
employee in Illinois had **no state income tax withheld at all**. That was an
honest fallback — a wrong guess is worse than nothing — but it meant the
product only worked in four states.

Writing forty-six more engine classes would have multiplied the same shape
forty-six times, and buried several hundred tax figures in Python where
nobody reviews them. Instead there is one engine, `TableDrivenStateEngine`,
and the per-state numbers live in reviewable JSON under
`app/services/state_tax/tables/`.

WA, CA, NY and OR keep their dedicated classes: their rules don't fit the
generic shape (Washington assesses L&I *per hour worked* by risk class,
Oregon layers on transit taxes). The registry prefers a dedicated engine
whenever one exists.

## Verification status — read this first

**Every table currently ships with `"verified": false`.** The figures are
approximations of the published 2026 schedules, good enough to exercise the
system and to be in the right neighbourhood, but nobody has checked them
against the source. Bracket edges, standard deductions, exemption amounts and
SUTA wage bases all change every year.

To see what's outstanding:

```
python -m app.services.state_tax.table_engine
```

```
47 state tax tables — 0 verified, 47 awaiting review

ST  METHOD    YEAR      SUTA BASE  OK  NAME
AK  none      2026          51700  --  Alaska
AL  brackets  2026           8000  --  Alabama
...
```

To verify a state: open its JSON, compare every figure against the `source`
URL in the file, correct what's wrong, then set `"verified": true` and update
`tax_year`. Verify the states you actually pay people in — you do not need
all forty-seven.

### Strict mode

Setting `PAYROLL_STRICT_TAX_TABLES=1` makes an unverified table withhold
**no** state income tax, and label the omission on the pay stub
(`IL income tax (unverified table — not applied)`) so it reads as a
deliberate gap rather than a no-income-tax state.

It is off by default, matching how the existing CA/NY/OR engines already
behave — their docstrings carry the same "2026-approximate, verify before
filing" disclaimer. A close-but-unconfirmed withholding is usually nearer the
truth than zero. Operators who would rather fail loud should turn it on.

Strict mode only suppresses *income tax*. Statutory premiums (NJ SDI, CO
FAMLI, RI TDI) and SUTA still apply, and states with no income tax at all are
untouched.

## Table schema

```jsonc
{
  "state": "IL",              // must match the filename
  "name": "Illinois",
  "tax_year": 2026,
  "verified": false,          // set true only after checking against `source`
  "source": "https://tax.illinois.gov/research/taxrates.html",
  "notes": "...",

  "income_tax": {
    "method": "flat",         // "none" | "flat" | "brackets"
    "rate": "0.0495",         // flat only
    "supplemental_rate": "0.0495",
    "standard_deduction": { "single": "0", "married": "0", "head_of_household": "0" },
    "exemption_allowance": { "single": "2850", "married": "5700", "head_of_household": "2850" },
    "brackets": {             // brackets only; [lower_bound, marginal_rate]
      "single": [["0", "0.02"], ["3000", "0.03"]],
      "married": [["0", "0.02"], ["6000", "0.03"]]
    }
  },

  "suta": {
    "wage_base": "13916",     // employer SUTA taxable wage base
    "default_rate": "0.0395"  // published NEW-EMPLOYER rate, a fallback only
  },

  "employee_other": [         // SDI / paid-leave premiums, employee side
    { "label": "NJ SDI", "rate": "0.0023", "wage_base": "165400" }
  ],
  "employer_other": []        // same shape, employer side
}
```

Notes on the schema:

- All money and rate values are **strings**, parsed to `Decimal`. This keeps
  exact decimal precision — never write them as JSON floats.
- Brackets are `[lower_bound, marginal_rate]` pairs, ascending, starting at
  `0`. Cumulative tax is derived by the engine, so a table cannot disagree
  with itself the way a transcribed "tax on the excess over" column can.
- A filing status missing from `brackets` falls back to `single`. Many states
  publish one schedule for everyone.
- `wage_base: null` on a premium means it applies to all wages, uncapped.
- Malformed tables raise `StateTaxTableError` on load — at startup or in
  tests, never partway through a pay run.

## Withholding math

Income tax for one pay period:

1. Annualize: `taxable × pay_periods`
2. Subtract `standard_deduction[filing_status]`
3. Subtract `exemption_allowance[filing_status]`
4. Apply the flat rate, or walk the bracket schedule
5. Divide back by `pay_periods`, round half-up to cents

Premiums are `rate × gross`, with the portion of gross still under
`wage_base` given the employee's YTD.

> **Known simplification.** `exemption_allowance` is a per-status annual
> amount. States that compute exemptions from allowances claimed on a state
> W-4 (IL-W-4, MI-W-4, etc.) need a per-employee allowance count, which the
> `Employee` model does not carry yet. The current values assume a single
> allowance, which over-withholds slightly for employees claiming more —
> conservative, but not exact. Adding a `state_allowances` column is
> follow-up work.

## SUTA rates

States assign each employer its own **experience rate**, which no library can
know. A single global `SUTA_RATE` was applied to every state, which is wrong
the moment you hire outside your home state — the wage bases alone range from
$7,000 (FL, AR) to $72,800 (WA).

Rate resolution, most specific first:

1. An explicit rate passed to the pay run
2. `SUTA_RATE_BY_STATE` — e.g. `SUTA_RATE_BY_STATE="WA:0.0121,OR:0.024"`
3. `SUTA_RATE`, when the stub is in `EMPLOYER_STATE`. An operator who set
   this means it for their home state, and it must outrank a published
   new-employer rate.
4. The state's `default_rate` (new-employer rate) from its table
5. `SUTA_RATE`, for a state with no table (WA/CA/NY/OR)

The wage base always comes from the engine for the **work** state.
Reciprocity moves income tax to the residence state but never unemployment
tax.

## Adding or fixing a state

1. Edit `app/services/state_tax/tables/<ST>.json`
2. Run `python -m app.services.state_tax.table_engine` to confirm it loads
3. Run `pytest tests/test_state_tax_tables.py`
4. If the state needs rules the schema can't express — per-hour assessments,
   local surtaxes, wage-bracket lookup tables — write a dedicated engine
   class instead and register it in `_DEDICATED` in
   `app/services/state_tax/__init__.py`

The arithmetic tests pin representative figures for IL (flat), VA (brackets)
and NJ (premiums). Those tests are *expected* to fail when you correct a
table — that's the point. Update the expected value in the same commit as
the table change, so every rate edit is a reviewed edit.

## Related docs

- [payroll-hr-module.md](payroll-hr-module.md) — the wider payroll/HR module
- [development.md](development.md) — running tests and linters
