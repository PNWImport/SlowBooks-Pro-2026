# Local / Municipal Payroll Taxes

The tax layer below the states: Pennsylvania EIT + LST, Ohio municipal and
school-district taxes, New York City and Yonkers, Maryland and Indiana county
taxes, Kentucky occupational license fees, Michigan city income taxes.

Same design as [state-tax-tables.md](state-tax-tables.md): one engine
(`app/services/local_tax/engine.py`), reviewable JSON data
(`app/services/local_tax/localities/*.json`), per-file provenance with a
`verified` flag, validation at load rather than mid-pay-run. Run
`python -m app.services.local_tax.engine` for the coverage report.

## Configuring an employee

Two fields on `Employee` (also settable per-stub via `PayStubInput`):

- `work_locality` — where the work happens (e.g. `PA-PHILADELPHIA`,
  `OH-COLUMBUS`, `KY-LOUISVILLE`)
- `residence_locality` — where the employee lives (e.g. `MD-MONTGOMERY`,
  `IN-MARION`, `OH-SD-BEXLEY`, `NY-NYC`)

Both nullable; null means "no local tax there". **Residency is never
assumed**: an employee whose `residence_locality` is unset withholds at the
work locality's *nonresident* rate — claiming a resident rate requires the
operator to set both fields to the same code. A code that matches no rule
withholds nothing but is surfaced in the calculation result's
`unknown_localities` so a typo is visible instead of a silent $0.

## Basis semantics

What a rule collects and where it attaches is its `basis`:

| basis | Attaches to | Used for |
|-------|-------------|----------|
| `work` | work locality; nonresident vs resident rate | OH municipal, KY occupational, Philadelphia |
| `residence` | residence locality, wherever the work is | MD counties, IN counties, OH school districts, NYC |
| `higher_of` | work locality, at max(work nonresident, residence resident) — PA Act 32 | PA EIT outside Philadelphia |
| `work_or_residence` | work city, plus residence city at resident rate less a credit | MI cities |

Amount kinds, orthogonal to basis: `percent` (rate × period taxable wages),
`brackets` (progressive annualized schedule — NYC), `percent_of_state_tax`
(the Yonkers resident surcharge). A rule may also carry `lst_per_year`
(PA Local Services Tax, level per-period installments at the work locality)
and `employer_rate` / `employer_flat_per_year` for employer-side levies.

A residence-basis rule with a `nonresident_rate` also taxes nonresidents who
work there on wages — that is Yonkers' nonresident earnings tax.

## Where the numbers land

- `PayStub.local_tax` (employee side — W-2 box 19), `local_tax_employer`
  (company expense), `work_locality` (box 20)
- W-2 boxes 18–20 populate from stub totals; multiple localities in one year
  are joined in box 20 (a per-locality row split is future work)
- The payroll JE credits "Local tax payable" against the 2370 → 2300 umbrella
  and debits employer-side local levies as payroll tax expense
- Local withholding counts as legally-required tax, so it reduces disposable
  earnings before garnishment limits are applied
- `GET /api/employees/{id}/ytd` includes a `local` total

## Known simplifications

- **Michigan residence-city credit** is the full work-city amount, floored at
  zero. Michigan actually caps the credit at what the residence city would
  charge at its nonresident rate on the same wages; the simplification
  over-credits, so it under-withholds slightly rather than over-withholding.
- **PA Act 32** compares the work nonresident rate with the residence
  resident rate only when both localities are on file. A PA employee living
  in a municipality we have no entry for withholds at the work rate alone —
  add their municipality (or use `PA-GENERIC-1PCT`) to fix.
- **LST low-income exemption** is not modelled; the flat amount always
  applies.
- **Verification**: every locality file ships `"verified": false`, exactly
  like the state tables. Local rates change more often than state ones —
  PA rates are set per municipality pair and OH school districts vote on
  levies. Verify against the collector's published rate, then flip the flag.

## Adding a locality

Append an entry to the state's file in
`app/services/local_tax/localities/` (or create a new `XX.json` with
`state`, `tax_year`, `verified`, `source`, `localities: []`), run the
coverage report to confirm it loads, and add an arithmetic pin to
`tests/test_local_tax.py` if the rate matters to you. Codes are free-form
but the convention is `ST-NAME` (`OH-SD-...` for school districts).
