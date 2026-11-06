"""Deterministic invoice arithmetic (SJ-12; decision SJ-D8).

Rules this module enforces:

* ``Decimal`` only — no floats anywhere; values arrive as strings or Decimals.
* Rounding policy: half-up to the currency's minor unit (``CURRENCY_EXPONENTS``; JPY 0).
* The currency is what the invoice states. No currency is assumed (never NZD by default);
  a missing, unknown or mixed currency blocks totals ("cannot compute").
* Tax is only what the invoice prints. No rate is assumed and no "tax included" guess is
  made; no tax-compliance determination is offered.
* A labour unit is never assumed to be an hour; a bare number is never assumed to be a price.
* Missing or illegible values are explicit unknowns that block the checks that need them.
* A discount line reduces the amount (its sign is normalised to negative and the check says so).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ISO 4217 minor-unit exponents for currencies an invoice is likely to state.
CURRENCY_EXPONENTS: dict[str, int] = {
    "NZD": 2, "AUD": 2, "USD": 2, "CAD": 2, "EUR": 2, "GBP": 2, "CHF": 2, "SGD": 2, "HKD": 2,
    "FJD": 2, "WST": 2, "TOP": 2, "PGK": 2, "SBD": 2, "CNY": 2, "INR": 2, "IDR": 2, "THB": 2,
    "PHP": 2, "MYR": 2, "ZAR": 2, "SEK": 2, "NOK": 2, "DKK": 2, "MXN": 2, "BRL": 2, "TWD": 2,
    "JPY": 0, "KRW": 0, "VND": 0, "ISK": 0, "CLP": 0, "XPF": 0, "VUV": 0, "XOF": 0, "XAF": 0,
    "BHD": 3, "KWD": 3, "OMR": 3, "JOD": 3, "TND": 3,
}  # fmt: skip
ROUNDING_POLICY = "half_up"
MAX_ABS = Decimal("9999999999.9999")  # Numeric(14, 4)
SYMBOLS = "$€£¥"

_AMOUNT_RE = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?$|^\(?-?\d+(?:\.\d+)?\)?$")
_CODE_RE = re.compile(r"^([A-Z]{3})\s*(.*)$|^(.*?)\s*([A-Z]{3})$")


class AmountError(ValueError):
    """A value that cannot be read as an exact decimal."""


def exponent(currency: str | None) -> int | None:
    return CURRENCY_EXPONENTS.get(currency) if currency else None


def valid_currency(code: str | None) -> bool:
    return bool(code) and code in CURRENCY_EXPONENTS


def to_decimal(value) -> Decimal | None:
    """Exact Decimal from a Decimal/int/str; floats are refused (they are not exact)."""
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise AmountError("floating-point values are not accepted; send amounts as strings")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    else:
        try:
            d = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise AmountError("not a number") from exc
    if not d.is_finite():
        raise AmountError("not a finite number")
    if abs(d) > MAX_ABS:
        raise AmountError("out of range")
    return d


def parse_amount(text: str | None) -> tuple[Decimal | None, str | None]:
    """Read printed text such as ``"1,234.50"``, ``"NZD 45.00"``, ``"$45"``, ``"(12.00)"`` or
    ``"-20.00"``. Returns ``(value, currency_code_if_printed)``. A ``$`` alone states no
    currency. Unreadable text returns ``(None, None)`` — never a guess."""
    if text is None:
        return None, None
    s = str(text).strip()
    if not s:
        return None, None
    code = None
    m = _CODE_RE.match(s)
    if m:
        if m.group(1) and m.group(1) in CURRENCY_EXPONENTS:
            code, s = m.group(1), m.group(2).strip()
        elif m.group(4) and m.group(4) in CURRENCY_EXPONENTS:
            code, s = m.group(4), m.group(3).strip()
    negative = False
    if s.startswith("-"):
        negative, s = True, s[1:].strip()
    s = s.lstrip(SYMBOLS).strip()
    if s.startswith("-"):
        negative, s = True, s[1:].strip()
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip().lstrip(SYMBOLS)
    if s.endswith("-"):  # "20.00-" credit notation
        negative, s = True, s[:-1]
    if not s or not _AMOUNT_RE.match(s):
        return None, None
    try:
        value = to_decimal(s.replace(",", ""))
    except AmountError:
        return None, None
    return (-value if negative else value), code


def quantize(value: Decimal, currency: str) -> Decimal:
    """Round half-up to the currency's minor unit."""
    exp = CURRENCY_EXPONENTS[currency]
    return value.quantize(Decimal(1).scaleb(-exp), rounding=ROUND_HALF_UP)


def fmt(value: Decimal | None, currency: str | None = None) -> str | None:
    """Plain string for an exact value; amounts show at least the currency's minor digits."""
    if value is None:
        return None
    normal = value.normalize()
    if normal == normal.to_integral():
        normal = normal.quantize(Decimal(1))
    exp = exponent(currency)
    if exp is not None and -normal.as_tuple().exponent < exp:
        normal = normal.quantize(Decimal(1).scaleb(-exp))
    return format(normal, "f")


def minor_to_major(amount_minor: int | None, currency: str | None) -> Decimal | None:
    if amount_minor is None or not valid_currency(currency):
        return None
    return Decimal(int(amount_minor)).scaleb(-CURRENCY_EXPONENTS[currency])


def policy_text(currency: str | None) -> str:
    exp = exponent(currency)
    if exp is None:
        return "Rounding half-up to the currency's minor unit; the currency is not known, so nothing is rounded."
    places = "no decimal places" if exp == 0 else f"{exp} decimal place{'s' if exp != 1 else ''}"
    return f"Rounding half-up to {places} ({currency} minor unit)."


# --------------------------------------------------------------------------- checks
@dataclass
class LineInput:
    id: str
    line_number: int
    kind: str
    quantity: Decimal | None
    unit: str | None
    unit_price: Decimal | None
    line_total: Decimal | None
    tax_printed: Decimal | None
    currency: str | None
    illegible: list[str] = field(default_factory=list)  # fields printed but unreadable


@dataclass
class InvoiceInput:
    currency: str | None
    subtotal: Decimal | None
    tax_printed: Decimal | None
    total: Decimal | None
    lines: list[LineInput]
    illegible: list[str] = field(default_factory=list)


def _diff(printed: Decimal, computed: Decimal) -> Decimal:
    return printed - computed


def line_check(line: LineInput, currency: str | None) -> dict:
    """Quantity × unit price versus the printed line total, for one line."""
    notes: list[str] = []
    result: dict = {
        "line_id": line.id,
        "line_number": line.line_number,
        "computed": None,
        "printed": fmt(line.line_total, currency),
        "difference": None,
        "amount_used": None,
        "status": "cannot_compute",
        "reasons": [],
        "notes": notes,
    }
    if line.kind == "labour" and not line.unit:
        notes.append("The labour unit is not stated; it is not assumed to be hours.")
    if line.illegible:
        result["reasons"].append("illegible_values")
    if currency is None:
        result["reasons"].append("currency_unknown")
        return result
    if line.currency and line.currency != currency:
        result["reasons"].append("mixed_currency")
        return result
    computed = None
    if line.quantity is not None and line.unit_price is not None:
        computed = quantize(line.quantity * line.unit_price, currency)
    sign = Decimal(1)
    if line.kind == "discount":
        sign = Decimal(-1)
        notes.append("A discount line reduces the amount.")
    if computed is not None:
        result["computed"] = fmt(computed, currency)
    if line.line_total is not None and computed is not None:
        if line.kind == "discount":  # printed sign conventions vary; compare magnitudes
            diff = _diff(abs(line.line_total), abs(computed))
        else:
            diff = _diff(line.line_total, computed)
        result["difference"] = fmt(diff, currency)
        result["status"] = "matches" if diff == 0 else "differs"
        used = line.line_total
    elif line.line_total is not None:
        result["status"] = "printed_only"
        if line.quantity is None:
            result["reasons"].append("missing_quantity")
        if line.unit_price is None:
            result["reasons"].append("missing_unit_price")
        used = line.line_total
    elif computed is not None:
        result["status"] = "computed_only"
        result["reasons"].append("missing_line_total")
        used = computed
    else:
        if line.quantity is None:
            result["reasons"].append("missing_quantity")
        if line.unit_price is None:
            result["reasons"].append("missing_unit_price")
        result["reasons"].append("missing_line_total")
        return result
    used = sign * abs(used) if line.kind == "discount" else used
    result["amount_used"] = fmt(used, currency)
    return result


def invoice_checks(inv: InvoiceInput) -> dict:
    """Line, subtotal and total checks against the printed values. Never guesses."""
    currency = inv.currency if valid_currency(inv.currency) else None
    line_currencies = {ln.currency for ln in inv.lines if ln.currency}
    if inv.currency and not valid_currency(inv.currency):
        currency_status = "unrecognised"
    elif currency is None and len(line_currencies) == 1 and valid_currency(next(iter(line_currencies))):
        # Not assumed: every line that states a currency prints the same one.
        currency, currency_status = next(iter(line_currencies)), "stated_on_lines"
    elif currency is None and line_currencies:
        currency_status = "mixed"
    elif currency is None:
        currency_status = "missing"
    elif line_currencies - {currency}:
        currency_status = "mixed"
    else:
        currency_status = "stated"
    known = currency_status in ("stated", "stated_on_lines")
    lines = [line_check(ln, currency) for ln in inv.lines]

    blockers: list[str] = []
    if not known:
        blockers.append(
            {"missing": "currency_unknown", "mixed": "mixed_currency", "unrecognised": "currency_unrecognised"}[
                currency_status
            ]
        )

    item_lines = [(ln, chk) for ln, chk in zip(inv.lines, lines, strict=True) if ln.kind != "tax"]
    tax_lines = [(ln, chk) for ln, chk in zip(inv.lines, lines, strict=True) if ln.kind == "tax"]
    lines_sum = None
    if not blockers:
        missing = [chk["line_number"] for _, chk in item_lines if chk["amount_used"] is None]
        if missing:
            blockers.append("line_amount_unknown")
        else:
            lines_sum = sum((Decimal(chk["amount_used"]) for _, chk in item_lines), Decimal(0))

    # Tax: printed only.
    tax_value, tax_source = None, "not_printed"
    if "tax_printed" in inv.illegible:
        tax_source = "unreadable"
    elif inv.tax_printed is not None:
        tax_value, tax_source = inv.tax_printed, "printed_total"
    elif tax_lines and all(chk["amount_used"] is not None for _, chk in tax_lines) and not blockers:
        tax_value = sum((Decimal(chk["amount_used"]) for _, chk in tax_lines), Decimal(0))
        tax_source = "tax_lines"
    elif tax_lines:
        tax_source = "unreadable"

    def _cmp(printed: Decimal | None, computed: Decimal | None, label: str) -> dict:
        out = {"printed": fmt(printed, currency), "computed": fmt(computed, currency), "difference": None}
        if blockers:
            out.update(status="cannot_compute", reasons=list(blockers))
        elif label in inv.illegible:
            out.update(status="cannot_compute", reasons=[f"{label}_illegible"])
        elif printed is None:
            out.update(status="not_printed", reasons=[f"{label}_not_printed"])
        elif computed is None:
            out.update(status="cannot_compute", reasons=[f"{label}_inputs_unknown"])
        else:
            diff = printed - computed
            out.update(status="matches" if diff == 0 else "differs", difference=fmt(diff, currency), reasons=[])
        return out

    subtotal_check = _cmp(inv.subtotal, lines_sum, "subtotal")
    base = inv.subtotal if inv.subtotal is not None else lines_sum
    total_notes: list[str] = []
    if tax_value is not None and base is not None:
        expected_total = base + tax_value
        total_notes.append("Expected total = subtotal (or line sum) + tax as printed.")
    elif tax_source == "unreadable":
        expected_total = None
        total_notes.append("The printed tax could not be read, so the total cannot be checked.")
    else:
        expected_total = base
        if tax_source == "not_printed":
            total_notes.append(
                "The invoice prints no tax amount, so the total is compared with the line sum only. "
                "Whether tax is included is not stated, and no tax rate is assumed."
            )
    total_check = _cmp(inv.total, expected_total, "total")
    total_check["notes"] = total_notes
    if tax_source in ("not_printed", "unreadable") and total_check["status"] == "differs":
        total_check["reasons"] = ["tax_not_stated"]

    status = "complete" if not blockers else "cannot_compute"
    return {
        "currency": currency if known else None,
        "currency_status": currency_status,
        "line_currencies": sorted(line_currencies),
        "rounding_policy": ROUNDING_POLICY,
        "rounding_policy_text": policy_text(currency if known else None),
        "status": status,
        "blockers": blockers,
        "lines": lines,
        "lines_sum": fmt(lines_sum, currency),
        "tax": {
            "printed": fmt(tax_value, currency),
            "source": tax_source,
            "note": "Tax is shown only as printed. First Mate does not assume a rate, whether tax is "
            "included, or whether the invoice meets tax requirements.",
        },
        "subtotal_check": subtotal_check,
        "total_check": total_check,
    }


def duplicate_candidates(lines: list[dict]) -> list[list[str]]:
    """Lines with the same normalised description, part number and amount. Candidates for a
    question only — never proof of duplicate charging."""
    groups: dict[tuple, list[str]] = {}
    for ln in lines:
        desc = re.sub(r"[^a-z0-9]+", " ", (ln.get("description") or "").lower()).strip()
        if not desc or ln.get("kind") in ("tax",):
            continue
        key = (desc, (ln.get("part_number") or "").lower(), ln.get("line_total"), ln.get("quantity"))
        groups.setdefault(key, []).append(ln["id"])
    return [ids for ids in groups.values() if len(ids) > 1]
