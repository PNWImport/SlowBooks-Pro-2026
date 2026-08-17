# ============================================================================
# EFW2 export — SSA electronic W-2 wage file (Specifications for Filing
# Forms W-2 Electronically, SSA Pub 42-007).
# ----------------------------------------------------------------------------
# Fixed-width 512-character records, one per line:
#
#   RA  Submitter          (1 per file)
#   RE  Employer           (1 per employer — this app is single-employer)
#   RW  Employee wage      (1 per employee)
#   RT  Total              (sums of the RW records)
#   RF  Final              (1 per file)
#
# Money fields are unsigned cents, zero-filled, no decimal point. Text
# fields are left-justified space-filled uppercase; unknown optional fields
# are blank.
#
# KNOWN LIMITATION — SSNs. This application deliberately stores only the
# last four SSN digits (see Employee.ssn_last_four), so RW positions 3-11
# are zero-filled, which Pub 42-007 permits for an unknown SSN but which
# the SSA will reject at scale. Before uploading: run the file through
# SSA's AccuWage Online, fill the real SSNs (the `warnings` list returned
# alongside the file names each employee), and verify the field layout
# against the current Pub 42-007 — positions shift between years.
# ============================================================================

from decimal import Decimal, ROUND_HALF_UP

from app.services.tax_forms.w2_w3 import compute_all_w2

RECORD_LENGTH = 512
CENT = Decimal("0.01")


def _money(value, width: int = 11) -> str:
    """Unsigned cents, zero-filled, no decimal point."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value or 0))
    cents = int((value.quantize(CENT, rounding=ROUND_HALF_UP)) * 100)
    if cents < 0:
        cents = 0
    text = str(cents)
    if len(text) > width:
        raise ValueError(f"money value {value} exceeds field width {width}")
    return text.rjust(width, "0")


def _alpha(value, width: int) -> str:
    """Left-justified, space-filled, uppercase, non-ASCII stripped."""
    text = (str(value) if value else "").upper()
    text = "".join(c for c in text if 32 <= ord(c) < 127)
    return text[:width].ljust(width)


def _digits(value, width: int) -> str:
    """Digits only, zero-filled right-justified."""
    text = "".join(c for c in str(value or "") if c.isdigit())
    return text[:width].rjust(width, "0")


class _Record:
    """A 512-char record assembled by (position, length) placement.

    Positions are 1-based as printed in Pub 42-007, so a transcription of
    the spec reads the same as the spec.
    """

    def __init__(self, identifier: str) -> None:
        self.chars = [" "] * RECORD_LENGTH
        self.place(1, 2, identifier)

    def place(self, pos: int, length: int, text: str) -> None:
        if len(text) != length:
            raise ValueError(f"field at {pos} expects {length} chars, got {len(text)}")
        self.chars[pos - 1 : pos - 1 + length] = list(text)

    def render(self) -> str:
        return "".join(self.chars)


def generate_efw2(db, year: int, company: dict) -> tuple[str, list[str]]:
    """Build the EFW2 file for a year → (file_content, warnings).

    `company` is the same dict the tax-form PDFs use (name, address, city,
    state, zip, ein). Raises ValueError when the EIN is missing — the file
    is unusable without it.
    """
    ein = "".join(c for c in str(company.get("ein") or "") if c.isdigit())
    if len(ein) != 9:
        raise ValueError(
            "A 9-digit employer EIN is required for EFW2 export — set it in "
            "Settings (company tax id) or EMPLOYER_EIN."
        )

    w2s = [w for w in compute_all_w2(db, year) if w.get("employee")]
    warnings: list[str] = []
    records: list[str] = []

    name = company.get("name") or ""
    address = company.get("address") or ""
    city = company.get("city") or ""
    state = (company.get("state") or "")[:2]
    zip_code = company.get("zip") or ""

    # --- RA: submitter (the employer submits for itself) ---
    ra = _Record("RA")
    ra.place(3, 9, _digits(ein, 9))  # submitter EIN
    ra.place(217, 57, _alpha(name, 57))  # submitter name
    ra.place(274, 22, _alpha(address, 22))  # location address
    ra.place(296, 22, _alpha("", 22))  # delivery address
    ra.place(318, 22, _alpha(city, 22))
    ra.place(340, 2, _alpha(state, 2))
    ra.place(342, 5, _digits(zip_code[:5], 5))
    records.append(ra.render())

    # --- RE: employer ---
    re_rec = _Record("RE")
    re_rec.place(3, 4, _digits(year, 4))  # tax year
    re_rec.place(8, 9, _digits(ein, 9))  # employer EIN
    re_rec.place(40, 57, _alpha(name, 57))  # employer name
    re_rec.place(97, 22, _alpha(address, 22))
    re_rec.place(141, 22, _alpha(city, 22))
    re_rec.place(163, 2, _alpha(state, 2))
    re_rec.place(165, 5, _digits(zip_code[:5], 5))
    records.append(re_rec.render())

    # --- RW: one per employee ---
    totals = {
        "wages": Decimal("0"),
        "federal": Decimal("0"),
        "ss_wages": Decimal("0"),
        "ss_tax": Decimal("0"),
        "medicare_wages": Decimal("0"),
        "medicare_tax": Decimal("0"),
    }
    for w2 in w2s:
        emp = w2["employee"]
        rw = _Record("RW")
        # SSN — zeros; the app stores only the last four digits.
        rw.place(3, 9, "0" * 9)
        warnings.append(
            f"RW for employee #{emp['id']} ({emp['name']}): SSN zero-filled — "
            "fill the real SSN before upload"
        )
        first = _alpha(emp.get("first_name"), 15)
        last = _alpha(emp.get("last_name"), 20)
        rw.place(12, 15, first)  # first name
        rw.place(27, 15, _alpha("", 15))  # middle
        rw.place(42, 20, last)  # last name
        rw.place(66, 22, _alpha(emp.get("address1"), 22))
        rw.place(110, 22, _alpha(emp.get("city"), 22))
        rw.place(132, 2, _alpha((emp.get("state") or "")[:2], 2))
        rw.place(134, 5, _digits((emp.get("zip") or "")[:5], 5))
        # Money fields (positions per Pub 42-007 RW layout).
        rw.place(188, 11, _money(w2["box1_federal_wages"]))  # wages
        rw.place(199, 11, _money(w2["box2_federal_tax_withheld"]))
        rw.place(210, 11, _money(w2["box3_ss_wages"]))
        rw.place(221, 11, _money(w2["box4_ss_tax_withheld"]))
        rw.place(232, 11, _money(w2["box5_medicare_wages"]))
        rw.place(243, 11, _money(w2["box6_medicare_tax_withheld"]))
        records.append(rw.render())

        totals["wages"] += w2["box1_federal_wages"]
        totals["federal"] += w2["box2_federal_tax_withheld"]
        totals["ss_wages"] += w2["box3_ss_wages"]
        totals["ss_tax"] += w2["box4_ss_tax_withheld"]
        totals["medicare_wages"] += w2["box5_medicare_wages"]
        totals["medicare_tax"] += w2["box6_medicare_tax_withheld"]

    # --- RT: totals across the RW records ---
    rt = _Record("RT")
    rt.place(3, 7, str(len(w2s)).rjust(7, "0"))  # number of RW records
    rt.place(10, 15, _money(totals["wages"], 15))
    rt.place(25, 15, _money(totals["federal"], 15))
    rt.place(40, 15, _money(totals["ss_wages"], 15))
    rt.place(55, 15, _money(totals["ss_tax"], 15))
    rt.place(70, 15, _money(totals["medicare_wages"], 15))
    rt.place(85, 15, _money(totals["medicare_tax"], 15))
    records.append(rt.render())

    # --- RF: final ---
    rf = _Record("RF")
    rf.place(8, 9, str(len(w2s)).rjust(9, "0"))  # number of RW records in file
    records.append(rf.render())

    return "\r\n".join(records) + "\r\n", warnings
