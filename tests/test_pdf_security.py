"""WeasyPrint call sites must not enable presentational hints.

PYSEC-2026-3412 is open against weasyprint 68.1 with no fixed release.
It is a CSS-injection issue that requires HTML presentational hints to be
enabled — unescaped attribute values get embedded into CSS. Every call
site currently invokes `write_pdf()` without `presentational_hints`,
which defaults to False, so the advisory does not apply to us.

That is a call-site property, not a library property, so it can be
undone by one well-meaning edit adding `presentational_hints=True` to fix
some legacy-HTML rendering quirk. This pins it.

It matters because the PDFs carry payroll data — W-2s, 1099s, 941s, SUI
wage reports, COBRA notices — rendered from templates interpolating
operator- and employee-supplied strings (company name, employee name,
addresses).
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _weasyprint_call_sites() -> list[tuple[Path, int, str]]:
    hits = []
    for path in APP.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if "write_pdf(" in line or re.search(r"\bHTML\s*\(", line):
                hits.append((path, lineno, line.strip()))
    return hits


def test_weasyprint_is_actually_used():
    """Guard the guard — if the scan finds nothing, the rest is vacuous."""
    assert len(_weasyprint_call_sites()) >= 5


def test_no_call_site_enables_presentational_hints():
    offenders = [
        f"{p.relative_to(APP.parent)}:{n}: {line}"
        for p, n, line in _weasyprint_call_sites()
        if "presentational_hints" in line and "False" not in line
    ]
    assert not offenders, (
        "presentational_hints enabled at a WeasyPrint call site, which is the "
        "precondition for PYSEC-2026-3412 (CSS injection via unescaped "
        "attribute values):\n  " + "\n  ".join(offenders)
    )


def test_pdf_renderers_use_the_safe_url_fetcher():
    """Separate hardening: the url_fetcher blocks WeasyPrint from resolving
    remote or file:// references pulled out of template content (SSRF /
    local-file read). Every string-rendered PDF should pass it."""
    missing = [
        f"{p.relative_to(APP.parent)}:{n}"
        for p, n, line in _weasyprint_call_sites()
        if "HTML(string=" in line and "url_fetcher" not in line
    ]
    assert not missing, (
        "WeasyPrint HTML(string=...) without url_fetcher=_safe_url_fetcher:\n  "
        + "\n  ".join(missing)
    )
