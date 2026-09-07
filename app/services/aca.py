# ============================================================================
# ACA reporting — 1095 coverage data + 1094 transmittal counts.
# ----------------------------------------------------------------------------
# Derives months-of-coverage per employee from benefit enrollments in
# MEC-providing medical plans. An employee is "covered" for a month when an
# enrollment spans at least one day of it (the IRS day-of-coverage rule is
# any day of the month). Self-insured plans list covered individuals
# (employee + dependents); fully-insured plans leave Part III to the
# carrier's 1095-B.
#
# JSON only — the machine-readable contract. Rendered 1095-C PDFs and the
# AIR e-file format are follow-ups in docs/todo.md. Verify against the
# current IRS instructions before filing; ACA codes (1A-1U offer codes,
# affordability safe harbors) are NOT derived here — offers of coverage
# aren't modelled, only actual enrollment.
# ============================================================================

from datetime import date, timedelta

from app.models.benefit_coverage import (
    BenefitEnrollment,
    BenefitKind,
    BenefitPlan,
    plan_kind_index,
)

MONTHS = list(range(1, 13))


def _covers_month(enrollment: BenefitEnrollment, year: int, month: int) -> bool:
    """True when the enrollment spans at least one day of the month."""
    month_start = date(year, month, 1)
    month_end = (
        date(year, 12, 31)
        if month == 12
        else date(year, month + 1, 1) - timedelta(days=1)
    )
    if enrollment.coverage_start and enrollment.coverage_start > month_end:
        return False
    if enrollment.coverage_end and enrollment.coverage_end < month_start:
        return False
    return True


def compute_1095_data(db, year: int) -> dict:
    """Per-employee coverage months for the year, plus 1094 counts."""
    # `kind` is encrypted, so it is filtered through its blind index. Comparing
    # BenefitPlan.kind to BenefitKind.MEDICAL here would compare the constant
    # against randomized ciphertext and silently return no enrollments at all
    # — an empty 1095 filing, which is exactly the kind of failure that looks
    # like "nobody had coverage" instead of like a bug.
    enrollments = (
        db.query(BenefitEnrollment)
        .join(BenefitPlan, BenefitEnrollment.plan_id == BenefitPlan.id)
        .filter(
            BenefitPlan.kind_bidx == plan_kind_index(BenefitKind.MEDICAL),
            BenefitPlan.provides_mec.is_(True),
        )
        .all()
    )

    by_employee: dict[int, dict] = {}
    for enrollment in enrollments:
        emp = enrollment.employee
        entry = by_employee.setdefault(
            enrollment.employee_id,
            {
                "employee_id": enrollment.employee_id,
                "name": emp.full_name if emp else None,
                "ssn_last_four": emp.ssn_last_four if emp else None,
                "months_covered": set(),
                "all_year": False,
                "plans": set(),
                "self_insured": False,
                "covered_individuals": [],
            },
        )
        entry["plans"].add(enrollment.plan.name)
        if enrollment.plan.self_insured:
            entry["self_insured"] = True
            names = {c["name"] for c in entry["covered_individuals"]}
            if entry["name"] not in names:
                entry["covered_individuals"].append(
                    {"name": entry["name"], "relationship": "self"}
                )
            for dep in enrollment.dependents:
                if dep.name not in names:
                    entry["covered_individuals"].append(
                        {
                            "name": dep.name,
                            "relationship": dep.relationship_kind,
                        }
                    )
        for month in MONTHS:
            if _covers_month(enrollment, year, month):
                entry["months_covered"].add(month)

    forms = []
    for entry in sorted(by_employee.values(), key=lambda e: e["employee_id"]):
        months = sorted(entry["months_covered"])
        forms.append(
            {
                "employee_id": entry["employee_id"],
                "name": entry["name"],
                "ssn_last_four": entry["ssn_last_four"],
                "months_covered": months,
                "all_12_months": months == MONTHS,
                "plans": sorted(entry["plans"]),
                "self_insured": entry["self_insured"],
                "covered_individuals": entry["covered_individuals"],
            }
        )

    # 1094 transmittal: form count + per-month covered-employee counts. The
    # ALE full-time-employee counts need hours analysis not modelled here.
    monthly_counts = {
        month: sum(1 for f in forms if month in f["months_covered"]) for month in MONTHS
    }
    return {
        "year": year,
        "form_count": len(forms),
        "monthly_covered_employee_counts": monthly_counts,
        "forms": forms,
        "note": (
            "Coverage months derive from actual enrollment; ACA offer codes "
            "and affordability safe harbors are not modelled. Verify against "
            "the current IRS 1094/1095 instructions before filing."
        ),
    }
