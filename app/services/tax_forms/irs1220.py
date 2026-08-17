# ============================================================================
# IRS Pub 1220 export — electronic 1099 file for the FIRE / IRIS systems.
# ----------------------------------------------------------------------------
# Fixed-width 750-character records, one per line:
#
#   T  Transmitter        (1 per file)
#   A  Payer              (1 per payer / return type — 1099-NEC here)
#   B  Payee              (1 per reportable vendor)
#   C  End of payer       (payee count + payment-amount totals)
#   F  End of file
#
# Money fields are unsigned cents, zero-filled, 12 wide. Payment Amount 1
# on the B record carries nonemployee compensation (1099-NEC box 1) —
# amount code "1" declared on the A record.
#
# Only vendors over the reporting threshold with a tax id on file are
# emitted; the rest come back in `warnings` so the operator can fix the
# vendor record and re-export. Verify the layout against the current
# Pub 1220 before uploading — positions and the TCC scheme shift between
# years, and a Transmitter Control Code (position 16 on T, blank here
# unless configured) is required for FIRE.
# ============================================================================

from decimal import Decimal, ROUND_HALF_UP

from app.services.form_1099 import compute_1099_data

RECORD_LENGTH = 750
CENT = Decimal("0.01")


def _money(value, width: int = 12) -> str:
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
    text = (str(value) if value else "").upper()
    text = "".join(c for c in text if 32 <= ord(c) < 127)
    return text[:width].ljust(width)


def _digits(value, width: int) -> str:
    text = "".join(c for c in str(value or "") if c.isdigit())
    return text[:width].rjust(width, "0")


class _Record:
    """750-char record assembled by 1-based (position, length) placement."""

    def __init__(self, identifier: str) -> None:
        self.chars = [" "] * RECORD_LENGTH
        self.place(1, 1, identifier)

    def place(self, pos: int, length: int, text: str) -> None:
        if len(text) != length:
            raise ValueError(f"field at {pos} expects {length} chars, got {len(text)}")
        self.chars[pos - 1 : pos - 1 + length] = list(text)

    def render(self) -> str:
        return "".join(self.chars)


def generate_1099_fire(
    db, year: int, payer: dict, tcc: str = ""
) -> tuple[str, list[str]]:
    """Build the Pub 1220 1099-NEC file → (file_content, warnings).

    `payer` is the company dict the 1099 PDFs already use. `tcc` is the
    five-character Transmitter Control Code the IRS assigns on FIRE
    enrollment; the file generates without one but cannot be uploaded.
    """
    tin = "".join(c for c in str(payer.get("ein") or "") if c.isdigit())
    if len(tin) != 9:
        raise ValueError(
            "A 9-digit payer EIN is required for the 1099 e-file — set it in "
            "Settings (company tax id) or EMPLOYER_EIN."
        )

    warnings: list[str] = []
    if not tcc:
        warnings.append(
            "No Transmitter Control Code configured — the IRS assigns one on "
            "FIRE enrollment; fill it before upload"
        )

    rows = compute_1099_data(db, year)
    payees = []
    for row in rows:
        if not row["reportable"]:
            continue
        payee_tin = "".join(c for c in str(row.get("tax_id") or "") if c.isdigit())
        if len(payee_tin) != 9:
            warnings.append(
                f"Vendor #{row['vendor_id']} ({row['name']}) skipped: no 9-digit "
                "tax id on file — collect a W-9 and re-export"
            )
            continue
        if not row["w9_on_file"]:
            warnings.append(
                f"Vendor #{row['vendor_id']} ({row['name']}): no W-9 on file "
                "(included anyway — tax id present)"
            )
        payees.append((row, payee_tin))

    year4 = _digits(year, 4)
    name = payer.get("name") or ""
    address = payer.get("address") or ""
    city = payer.get("city") or ""
    state = (payer.get("state") or "")[:2]
    zip_code = (payer.get("zip") or "")[:9]

    records: list[str] = []

    # --- T: transmitter ---
    t = _Record("T")
    t.place(2, 4, year4)
    t.place(7, 9, _digits(tin, 9))  # transmitter TIN
    t.place(16, 5, _alpha(tcc, 5))  # Transmitter Control Code
    t.place(30, 40, _alpha(name, 40))  # transmitter name
    t.place(110, 40, _alpha(name, 40))  # company name
    t.place(190, 40, _alpha(address, 40))
    t.place(230, 40, _alpha(city, 40))
    t.place(270, 2, _alpha(state, 2))
    t.place(272, 9, _alpha(zip_code, 9))
    t.place(296, 8, _digits(len(payees), 8))  # total payees in file
    records.append(t.render())

    # --- A: payer (return type NE = 1099-NEC, amount code 1) ---
    a = _Record("A")
    a.place(2, 4, year4)
    a.place(12, 9, _digits(tin, 9))  # payer TIN
    a.place(26, 2, _alpha("NE", 2))  # type of return: 1099-NEC
    a.place(28, 18, _alpha("1", 18))  # amount codes used
    a.place(52, 40, _alpha(name, 40))  # payer name
    a.place(134, 40, _alpha(address, 40))
    a.place(174, 40, _alpha(city, 40))
    a.place(214, 2, _alpha(state, 2))
    a.place(216, 9, _alpha(zip_code, 9))
    records.append(a.render())

    # --- B: one per reportable payee ---
    total_paid = Decimal("0")
    for row, payee_tin in payees:
        b = _Record("B")
        b.place(2, 4, year4)
        # TIN type: 1 = EIN, 2 = SSN. A vendor with a company name is
        # presumed to be a business (EIN); an individual, an SSN.
        tin_type = "1" if row.get("company") else "2"
        b.place(11, 1, tin_type)
        b.place(12, 9, _digits(payee_tin, 9))
        # Payment Amount 1 — nonemployee compensation.
        b.place(55, 12, _money(row["total_paid"]))
        payee_name = row.get("company") or row.get("name") or ""
        b.place(288, 40, _alpha(payee_name, 40))
        # Address lines come pre-joined from _vendor_address; first 40 chars
        # go in the mailing-address field, the city/state/zip fields stay
        # blank rather than guessing a split.
        b.place(368, 40, _alpha(row.get("address"), 40))
        records.append(b.render())
        total_paid += row["total_paid"]

    # --- C: end of payer ---
    c = _Record("C")
    c.place(2, 8, _digits(len(payees), 8))  # number of payees
    c.place(16, 18, _money(total_paid, 18))  # control total, amount 1
    records.append(c.render())

    # --- F: end of file ---
    f = _Record("F")
    f.place(2, 8, _digits(1, 8))  # number of A records
    f.place(22, 8, _digits(len(payees), 8))
    records.append(f.render())

    return "\r\n".join(records) + "\r\n", warnings
