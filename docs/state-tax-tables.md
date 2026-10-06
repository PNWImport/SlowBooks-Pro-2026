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

## Independent checks on 2026-10-05

Federal withholding now uses all six annual percentage-method schedules in
[IRS Publication 15-T (2026)](https://www.irs.gov/publications/p15t), including
published base-tax amounts at rounded checkbox thresholds. Worksheet 1A's
$8,600/$12,900 adjustments were already correct. Known-answer tests cover all
42 published taxable rows, all six filing-status/job-checkbox combinations,
zero bands, and W-4 income, deductions, credits, and extra withholding.

Washington PFML now uses 1.13%, the 71.43% employee/28.57% employer split, and a
$184,500 annual wage cap from [ESD's employer guidance](https://paidleave.wa.gov/employer-roles-responsibilities/).
Both PFML and WA Cares exclude reported and paycheck tips from current and
earlier year-to-date premium wages. [WA Cares guidance](https://wacaresfund.wa.gov/help-support/frequently-asked-questions)
uses the same wage definition and a 0.58% rate without a cap. Income-tax
reductions do not suppress these gross-wage/hour assessments. The $78,200
Washington unemployment base already matched [ESD's 2026 table](https://esd.wa.gov/employer-requirements/unemployment-taxes/how-we-determine-tax-rates).
Regressions cover cap crossings, tips, voided pay exclusion, and persisted
regular, retro, gross-up, and termination paychecks. Termination year-to-date
wages exclude processed checks dated after the payout.

CO/MA/DE paid-leave items now use the $184,500 [2026 Social Security base](https://www.ssa.gov/OACT/cola/cbbdet.html).
The programs' cap rules were checked against [Colorado FAMLI's wage-cap notice](https://content.govdelivery.com/accounts/CODLE/bulletins/3c9e0c5),
[Massachusetts contribution guidance](https://www.mass.gov/info-details/pfml-registration-contributions-and-payments),
and [Delaware's statutory wage definition](https://delcode.delaware.gov/title19/c037/).
The existing Colorado 0.88% split equally, Massachusetts 0.46% employee/0.42%
employer, and Delaware 0.40% employee/0.40% employer rates are unchanged.
Boundary tests cover the former cap, crossing $184,500, and wages at/above it.

California SDI now uses [EDD's 2026 rate](https://edd.ca.gov/en/payroll_taxes/rates_and_withholding/)
of 1.3% without an annual cap. New York PFL now uses the [official 2026 rate and cap](https://paidfamilyleave.ny.gov/2026)
of 0.432% and $411.91. New York unemployment now uses the [DOL 2026 wage base](https://dol.ny.gov/nys-45-quarterly-reporting)
of $17,600, with old-cap, crossing, and at-cap regressions. Oregon
unemployment already used the [correct $56,700 base](https://www.oregon.gov/employ/businesses/pages/current-tax-rate.aspx); its catalog documentation is updated. Gross-based CA SDI, NY SDI/PFL, and Oregon transit
assessments continue when income-tax wages are zero. Oregon's 0.1% transit
rate already matched [DOR guidance after the May 2026 referendum](https://www.oregon.gov/dor/programs/businesses/pages/statewide-transit-tax.aspx).
Tests use published examples and annual-cap boundaries, independently of the
production constants.

## Remaining release limits

These checks verify the named rates, caps, and calculation paths; they do not
verify every supported state's income-tax formula. CA/NY/OR income schedules
remain simplified approximations, including limited filing-status, allowance,
and credit handling. Independently reconcile any deployed state's official
withholding method and representative paychecks before real payroll.

Employer-size classifications, private-plan approvals, and employee exemptions
are not configurable in the current calculators. They apply the standard
employer share. Washington employers below 50 generally owe no employer PFML
share unless covered by the small-business assistance-grant rule; Colorado
employers with 9 or fewer employees owe no employer FAMLI share; Massachusetts
employers below 25 covered individuals owe no employer PFML share. Delaware employers below 10 are generally excluded; employers with
10–24 employees generally owe parental-leave contributions only, while 25+
are covered by all leave programs under [Delaware law](https://delcode.delaware.gov/title19/c037/). Approved
WA Cares exemptions also require withholding to stop. Confirm eligibility
against [Washington](https://paidleave.wa.gov/employer-roles-responsibilities/),
[Colorado](https://content.govdelivery.com/accounts/CODLE/bulletins/4044121),
[Massachusetts](https://www.mass.gov/info-details/paid-family-and-medical-leave-employer-contribution-rates-and-calculator),
and [WA Cares](https://wacaresfund.wa.gov/how-it-works) sources. A deployment that
needs one of these rules must implement and test the appropriate configuration
before using the calculator for live payroll.

The Oregon dedicated engine now calculates the standard 2026 Paid Leave
contribution: employee 0.6% and employer 0.4%, capped at $184,500 of annual
subject wages, alongside the existing income and transit taxes. These rates
and the cap match the [official contribution calculator](https://paidleave.oregon.gov/employers/contributions-calculator.html).
Unlike Washington, Oregon includes reported and paycheck tips. Qualified
Section 125 health/FSA/HSA exclusions reduce the current and cumulative subject
bases; ordinary employee retirement salary deferrals do not. The calculator
uses the supported benefits' FICA wage bases and immutable `PayStubBenefit`
snapshots, not income-tax wages or total pre-tax deductions. The [Paid Leave
wage guidance](https://paidleave.oregon.gov/resources/) defines these covered
and excluded wage categories.

This is the standard covered, large-employer mode. Oregon's 25-employee
threshold is the prior year's average monthly worldwide headcount, with
temporary leave replacements excluded, not today's active employee count.
Small employers generally owe no employer share unless an assistance grant
requires it; approved equivalent plans and employee coverage exclusions also
change obligations. These classifications, employer pickup of employee
contributions, and wage-localization changes across states are not modelled.
The supported calculation assumes Oregon-covered wages throughout the calendar
year; it does not decide which historical wages qualify after a change in
employment localization. Review the [employer guidebook](https://d1o0i0v5q5lp8h.cloudfront.net/paidleave/live/assets/resources/Paid-Leave-Oregon-Employer-Guidebook-EN.pdf)
and [size instructions](https://d1o0i0v5q5lp8h.cloudfront.net/paidleave/live/assets/resources/PaidLeave-Employer-Size-Instructions-EN.pdf)
before live Oregon payroll. A deployment needing these rules must implement
and test the corresponding classification support first.

Payroll now reconstructs cumulative FICA/FUTA wage bases from immutable
`PayStubBenefit` amounts and `reduces_fica` flags, plus explicitly recorded
ordinary taxable employer amounts, preserving the treatment of processed
checks after benefit-plan changes. Traditional 401(k) deferrals and income-only
ad-hoc deductions remain in FICA wages. All regular, retroactive, gross-up and
termination calculations receive these historical bases.
Only processed checks consume cumulative payroll wage bases. Already paid
checks on the same pay date count; unpaid drafts and voids do not.
[IRS Publication 15](https://www.irs.gov/publications/p15),
[Publication 15-B](https://www.irs.gov/publications/p15b), and the
[Additional Medicare FAQ](https://www.irs.gov/businesses/small-businesses-self-employed/questions-and-answers-for-the-additional-medicare-tax)
provide the applicable exclusions and thresholds. Known-answer regressions
cover prior gross of $180,000 with $15,000 qualified exclusions followed by a
$10,000 check ($620 Social Security); prior gross of $205,000 with $20,000
exclusions followed by $10,000 ($145 Medicare); and prior gross of $7,500 with
$2,000 exclusions followed by $1,000 ($6 effective FUTA).

Legacy or imported checks lacking those snapshots retain stored gross as their
FICA basis. Their aggregate pre-tax deduction may include 401(k) amounts and
cannot reveal historical qualified exclusions. Old employer-taxable flags
without an explicit treatment and amount marker do not add noncash wages.
Such records require an explicit historical-record policy before relying on
annual caps or Additional Medicare calculations. Do not infer past exclusions
or fringe valuation from current benefit codes, total deductions or rounded
taxes already charged. This remains a release limit for unsupported history;
the snapshot correction does not establish broad payroll readiness.

New drafts record their paid-history baseline and payroll writes serialize
per employee. If another check is processed first, processing the stale draft
returns 409 without changing or posting it. Cancel and recreate the draft to
recalculate against paid wages. With $184,000 already paid, two $1,000 drafts
initially each calculate $31 Social Security; after paying the first, the
second is held, and its replacement calculates $0. Cancellation refunds
recorded benefit reservations exactly. Legacy drafts without a verifiable
baseline or positive-benefit reservation marker require reconciliation.

Ordinary noncash employer contributions now support explicit `fully_taxable`
treatment. A $100 contribution on $2,000 cash pay supplies $2,100 tax wages,
$130.20 Social Security and $30.45 Medicare, while cash gross remains $2,000.
The immutable classification and amount snapshot supplies W-2/941/940 and
state reporting; changing the current code cannot reinterpret the paid check.
Old `employer_taxable` flags are not automatically classified. New positive
unclassified contributions return 422. This mode applies only when the entire
resolved employer contribution cost equals the applicable ordinary taxable
value across all modeled wage bases. The benefit expense/liability is posted
once; the noncash amount is not a second cash wage or net-pay addition.
[IRS Publication 15-B](https://www.irs.gov/publications/p15b) describes special
valuation and exclusions: employer cost is not automatically taxable value.
Group-term life insurance, other special fringe rules, taxable post-tax
matches, employer-paid employee-tax gross-ups, and insufficient cash remain
unsupported. Historical incorrect withholding still needs reconciliation.

See the [continued beta checklist](beta-continuation-2026-10-05.md) for the
current source/image provenance and verified calculation scope. These scoped
corrections do not establish filing, legal or all-jurisdiction readiness.
