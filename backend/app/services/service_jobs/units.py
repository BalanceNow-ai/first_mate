"""Central length parsing and conversion for service-job measurements (SJ-04).

* The text the person wrote ("25", "1 1/4\"", "0.8 m", "20–32 mm") is kept verbatim by the
  caller; this module only interprets it.
* Conversion to millimetres uses exact factors (1 in = 25.4 mm, 1 ft = 304.8 mm). It never
  adds precision: the *resolution* implied by what was written (the last written digit, or
  the fraction's denominator) travels with the value, so "0.8 m" is "800 mm, nearest 100 mm",
  not a measurement to the millimetre.
* Threads are not lengths: :func:`parse_thread` only splits standard / size / pitch out of
  the written text and never infers compatibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

TO_MM: dict[str, Decimal] = {
    "mm": Decimal(1),
    "cm": Decimal(10),
    "m": Decimal(1000),
    "in": Decimal("25.4"),
    "ft": Decimal("304.8"),
}
LENGTH_UNITS = tuple(TO_MM)
_ALLOWED_DENOMINATORS = {2, 4, 8, 16, 32, 64}
_MM_PLACES = Decimal("0.0001")  # storage scale (Numeric(14, 4)); far below any written resolution

_UNIT_RE = r"(mm|millimet(?:re|er)s?|cm|centimet(?:re|er)s?|met(?:re|er)s?|m|inch(?:es)?|in|\"|″|ft|foot|feet|'|′)"
_NUM_RE = r"(\d+[ -]\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_LENGTH_RE = re.compile(
    rf"^\s*{_NUM_RE}\s*{_UNIT_RE}?\s*(?:(?:-|–|—|to)\s*{_NUM_RE}\s*{_UNIT_RE}?)?\s*$",
    re.IGNORECASE,
)


class UnitError(ValueError):
    """The written value cannot be interpreted as a length without guessing."""


def canonical_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    u = unit.strip().lower()
    if not u:
        return None
    if u in ("mm",) or u.startswith("millimet"):
        return "mm"
    if u in ("cm",) or u.startswith("centimet"):
        return "cm"
    if u in ("m",) or u.startswith("metre") or u.startswith("meter"):
        return "m"
    if u in ("in", '"', "″") or u.startswith("inch"):
        return "in"
    if u in ("ft", "foot", "feet", "'", "′"):
        return "ft"
    raise UnitError(f"Unsupported unit {unit!r}; use mm, cm, m, in or ft")


def _number(text: str) -> tuple[Decimal, Decimal]:
    """(value, resolution) for "25", "25.5", "3/4", "1 1/4", "1-1/4"."""
    text = text.strip()
    whole = Decimal(0)
    frac = text
    m = re.fullmatch(r"(\d+)[ -](\d+/\d+)", text)
    if m:
        whole, frac = Decimal(m.group(1)), m.group(2)
    if "/" in frac:
        num, den = (int(p) for p in frac.split("/"))
        if den not in _ALLOWED_DENOMINATORS or num <= 0:
            raise UnitError(f"Fraction {frac!r} is not a usual measuring fraction (halves … 64ths)")
        return whole + Decimal(num) / Decimal(den), Decimal(1) / Decimal(den)
    try:
        value = Decimal(frac)
    except InvalidOperation as exc:  # pragma: no cover - regex guarantees digits
        raise UnitError(f"Cannot read {text!r} as a number") from exc
    exponent = value.as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    return value, Decimal(1).scaleb(-places)


def fmt(value: Decimal | None) -> str | None:
    """Plain decimal text without trailing zeros or exponent ("800", "31.75")."""
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return text


def _fraction_text(resolution: Decimal) -> str:
    if resolution < 1 and (Decimal(1) / resolution) == (Decimal(1) / resolution).to_integral_value():
        den = int(Decimal(1) / resolution)
        if den in _ALLOWED_DENOMINATORS:
            return f"1/{den}"
    return fmt(resolution) or "1"


@dataclass(frozen=True)
class Length:
    value_min: Decimal
    value_max: Decimal
    unit: str
    resolution: Decimal  # in ``unit``, implied by what was written
    normalized_min_mm: Decimal
    normalized_max_mm: Decimal
    resolution_mm: Decimal

    @property
    def is_range(self) -> bool:
        return self.value_min != self.value_max

    def implied_precision(self) -> str:
        return f"as written: nearest {_fraction_text(self.resolution)} {self.unit}"


def to_mm(value: Decimal, unit: str) -> Decimal:
    return (value * TO_MM[unit]).quantize(_MM_PLACES)


def parse_length(text: str, unit: str | None = None) -> Length:
    """Interpret a written length or range. ``unit`` (if given) applies when the text has none;
    a unit in the text that disagrees with ``unit`` is an error, never silently resolved."""
    if not text or len(text) > 60:
        raise UnitError("Enter the value as written, e.g. 25, 1 1/4 or 20-32")
    m = _LENGTH_RE.match(text)
    if not m:
        raise UnitError(f"Cannot read {text!r} as a length; write e.g. 25 mm, 1 1/4 in or 20-32 mm")
    n1, u1, n2, u2 = m.groups()
    explicit = canonical_unit(unit)
    units = {canonical_unit(u) for u in (u1, u2) if u}
    if explicit:
        units.add(explicit)
    if len(units) > 1:
        raise UnitError("The value and unit disagree (e.g. a value in inches with unit mm)")
    if not units:
        raise UnitError("A unit is required (mm, cm, m, in or ft)")
    canon = units.pop()
    v1, r1 = _number(n1)
    v2, r2 = _number(n2) if n2 else (v1, r1)
    if v2 < v1:
        raise UnitError("A range must be written low to high")
    resolution = max(r1, r2)
    return Length(
        value_min=v1,
        value_max=v2,
        unit=canon,
        resolution=resolution,
        normalized_min_mm=to_mm(v1, canon),
        normalized_max_mm=to_mm(v2, canon),
        resolution_mm=to_mm(resolution, canon),
    )


_THREAD_STANDARDS = (
    ("BSPT", "BSPT"),
    ("BSPP", "BSPP"),
    ("BSP", "BSP"),
    ("NPTF", "NPTF"),
    ("NPT", "NPT"),
    ("NPS", "NPS"),
    ("UNC", "UNC"),
    ("UNF", "UNF"),
    ("JIC", "JIC"),
    ("ORB", "ORB"),
)


def parse_thread(text: str | None) -> dict:
    """Split the written thread designation into standard / size / pitch where the text says
    so. Unknown parts stay None; nothing about fit or compatibility is inferred."""
    out = {"standard": None, "size": None, "pitch": None}
    if not text:
        return out
    t = text.strip()
    m = re.fullmatch(r"M(\d+(?:\.\d+)?)(?:\s*[x×]\s*(\d+(?:\.\d+)?))?", t, re.IGNORECASE)
    if m:
        out.update(standard="metric", size=f"M{m.group(1)}", pitch=f"{m.group(2)} mm" if m.group(2) else None)
        return out
    upper = t.upper()
    for token, name in _THREAD_STANDARDS:
        if re.search(rf"\b{token}\b", upper):
            out["standard"] = name
            size = re.sub(rf"\b{token}\b", "", t, flags=re.IGNORECASE).strip(" -")
            tpi = re.search(r"-(\d+)\s*$", size)
            if tpi and name in ("UNC", "UNF"):
                out["pitch"] = f"{tpi.group(1)} TPI"
                size = size[: tpi.start()].strip()
            out["size"] = size or None
            return out
    return out
