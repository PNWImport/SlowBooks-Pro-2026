# Accessibility

SlowBooks Pro is built to be usable by everyone, including people who rely
on screen readers, keyboards, or high-contrast displays. We **strive to
conform to WCAG 2.1 Level AA**. We do not claim compliance — no certifying
body issues one — but we test against it, fix what we find, and treat a
barrier as a bug.

![The Company Snapshot split down the middle: the light theme on the left, the dark theme on the right, with the same figures and the same A/R aging colour key in both](../screenshots/a11y-split.png)

- Every data table declares its column headers (`scope="col"`).
- Icon-only buttons (remove a line, delete an attachment, close a dialog)
  carry accessible names.
- Notifications ("Invoice saved") announce through a polite live region.
- Dialogs are real dialogs: focus moves into them, Tab and Shift+Tab stay
  inside, Escape closes them, and focus returns to the control that opened
  them.
- State is never conveyed by colour alone (e.g. the reconciliation
  difference reads "Balanced" / "Out of balance").
- Muted text meets the 4.5:1 contrast ratio in both the light and dark
  themes.
- The shared PDF renderer requests PDF/UA-1 tagging. COBRA and state SUI
  reports also use that renderer. If tagged rendering fails, it falls back
  to an ordinary PDF; tagging and full PDF/UA conformance are not guaranteed.

## Browser checks October 5 2026

The fresh local Chromium beta pass rendered 61 static route views in both desktop themes
and ran 122 axe-core WCAG A/AA audits with zero confirmed violations after
fixing field names and small import/report controls. Twenty additional tablet
and narrow-viewport renders were observations of the desktop interface, not
mobile/reflow acceptance. Eleven live workflow checks passed. Dialog checks
exercise contrast, accessible names, focus trapping, Escape, and remembered HR
tabs. See the [current beta checklist](beta-readiness-2026-10-05.md).

An isolated clone added 32 both-theme render/axe checks covering all 12
parameterized detail routes, the check-register alias, and three actual
nonprofit pages. Those checks also had zero confirmed violations, page
exceptions or HTTP 5xx. They retain 32 contrast-rule occurrences and 20
close-button glyph/name occurrences for manual review; those are audit
occurrences, not a count of distinct defects.

The full suite subsequently caught shared IIF/QBO error and warning notices
with insufficient dark-theme contrast. Theme colors corrected the issue, and
the existing regression now renders both result states explicitly. Sixteen
checks against the rebuilt image passed with contrast ratios 5.05–7.62.

The continued payroll checks exercise the three employer-tax treatment choices
and Cancel draft. A persistent Chromium case confirms cancellation removes
Process/Cancel after reload; independent checks cover both themes, the actual
readonly page/server restriction, visible stale-history guidance and restaging
at the Social Security cap. The cancel target passes axe's spacing criterion;
its observed 17-pixel height is not a claim that it meets a 24-pixel size rule.
See the [continued beta checklist](beta-continuation-2026-10-05.md) for build
provenance. These checks supplement the earlier 154 audit occurrences.

Automated manual-review items remain: gradient/glyph contrast on each audited
route, the QBO import-log scroll area's generic-element name, and an empty QBO
log table. These are retained separately from confirmed violations. Automated
checks do not establish WCAG conformance or replace assistive technology testing.

## What we know is still open

- Human screen-reader testing, full keyboard workflow acceptance, manual
  gradient/glyph contrast review, and PDF/UA assessment remain outstanding.
  Browser checks and PDF structure checks are not a conformance assessment.
- The chart-of-accounts tree and some long entry forms could use landmark
  regions and skip links.
- Colour-coding on the dashboard charts has text equivalents in the legend
  but not on the bars themselves.
- Keyboard-only drag ordering is not offered where a mouse drag exists
  (the dashboard uses arrow buttons instead).

## Tell us

If something in SlowBooks Pro is hard or impossible for you to use, open
an issue at https://github.com/VonHoltenCodes/SlowBooks-Pro-2026/issues or
email trent@neonpulsetechshop.com and say which screen and which assistive
technology. Barriers are triaged as bugs.

The same statement, with more screenshots, is on the website:
https://www.slowbookspro.com/accessibility/
