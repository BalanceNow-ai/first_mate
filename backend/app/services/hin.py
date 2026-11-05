"""Hull Identification Number (HIN / CIN) decoding.

Supported structures (12 characters after removing spaces/hyphens, optionally preceded
by a two-letter country code as in ISO 10087, e.g. ``NZ-ABC12345D404``):

* **Current format** (USCG 33 CFR 181.25, since 1 Aug 1984; same layout as ISO 10087):
  MIC (3) · serial (5) · production month letter A–L (1) · last digit of production
  year (1) · model year (2).
* **Legacy model-year format** (pre-Aug-1984 US): MIC · serial · ``M`` · model year (2)
  · production month letter A–L.
* **Legacy straight-year format** (pre-Aug-1984 US): MIC · serial · four digits holding a
  production month (01–12) and a two-digit production year (72–84). Because those two
  ranges never overlap the date is decoded only when exactly one reading is valid.

The manufacturer is reported **only** when the MIC is recorded against exactly one
manufacturer in ``manufacturers.mic_codes``. Nothing about the boat's model or
equipment is ever inferred from a HIN. Anything ambiguous is returned as ``null``
with a warning.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.boat_db import Manufacturer

MONTH_LETTERS = "ABCDEFGHIJKL"  # A = January … L = December
_FORBIDDEN = set("IOQ")  # USCG: I, O and Q are not used in a HIN
_CHARS = re.compile(r"^[A-Z0-9]+$")
_CURRENT = re.compile(r"^([A-Z0-9]{3})([A-Z0-9]{5})([A-L])(\d)(\d{2})$")
_MODEL_YEAR = re.compile(r"^([A-Z0-9]{3})([A-Z0-9]{5})M(\d{2})([A-L])$")
_STRAIGHT = re.compile(r"^([A-Z0-9]{3})([A-Z0-9]{5})(\d{2})(\d{2})$")


@dataclass
class HinDecode:
    input: str
    normalized: str | None = None
    valid: bool = False
    status: str = "invalid"  # valid | invalid | unrecognised
    format: str | None = None  # iso_10087 | us_current | us_legacy_model_year | us_legacy_straight_year
    country_code: str | None = None
    mic: str | None = None
    serial: str | None = None
    production_month: int | None = None
    production_year: int | None = None
    model_year: int | None = None
    manufacturer: dict | None = None  # {"id", "name", "is_synthetic"} when the MIC is recorded
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _clean(raw: str) -> str:
    return re.sub(r"[\s\-_.]+", "", raw or "").upper()


def _model_year_from_two_digits(yy: int, today: date) -> int | None:
    """Current format began with model year 1985; model years run to next year."""
    for century in (2000, 1900):
        candidate = century + yy
        if 1985 <= candidate <= today.year + 1:
            return candidate
    return None


def decode_structure(raw: str, today: date | None = None) -> HinDecode:
    """Pure structural decode (no database lookups)."""
    today = today or date.today()
    result = HinDecode(input=raw)
    cleaned = _clean(raw)
    if not cleaned:
        result.warnings.append("No HIN supplied")
        return result

    country = None
    body = cleaned
    if len(cleaned) == 14 and cleaned[:2].isalpha():
        country, body = cleaned[:2], cleaned[2:]
    if len(body) != 12:
        result.warnings.append("A HIN has 12 characters (optionally preceded by a 2-letter country code)")
        return result
    if not _CHARS.match(body):
        result.warnings.append("A HIN may only contain letters and digits")
        return result
    bad = sorted(_FORBIDDEN & set(body))
    if bad:
        result.warnings.append(f"Letters {', '.join(bad)} are never used in a HIN — check for 1/0 typing errors")
        return result

    result.country_code = country
    result.normalized = f"{country}-{body}" if country else body
    result.mic, result.serial = body[:3], body[3:8]

    m = _CURRENT.match(body)
    if m:
        result.format = "iso_10087" if country else "us_current"
        month = MONTH_LETTERS.index(m.group(3)) + 1
        year_digit = int(m.group(4))
        model_year = _model_year_from_two_digits(int(m.group(5)), today)
        if model_year is None:
            result.status = "unrecognised"
            result.warnings.append("Model year characters do not form a plausible model year")
            return result
        result.model_year = model_year
        result.production_month = month
        # Production happens in the model year or the calendar year before it.
        candidates = [y for y in (model_year - 1, model_year) if y % 10 == year_digit]
        if len(candidates) == 1:
            result.production_year = candidates[0]
            result.confidence = 0.9
        else:
            result.confidence = 0.5
            result.warnings.append(
                "Production year digit is inconsistent with the model year; production year not decoded"
            )
        if result.production_year and date(result.production_year, month, 1) > today:
            result.production_year = None
            result.production_month = None
            result.confidence = 0.5
            result.warnings.append("Decoded production date is in the future; production date not decoded")
        result.valid = True
        result.status = "valid"
        return result

    if country is None:
        m = _MODEL_YEAR.match(body)
        if m:
            yy = int(m.group(3))
            if 72 <= yy <= 84:
                result.format = "us_legacy_model_year"
                result.model_year = 1900 + yy
                result.production_month = MONTH_LETTERS.index(m.group(4)) + 1
                result.confidence = 0.7
                result.valid = True
                result.status = "valid"
                result.warnings.append("Pre-1984 model-year format; production year is not encoded")
                return result
        m = _STRAIGHT.match(body)
        if m:
            a, b = int(m.group(3)), int(m.group(4))
            readings = []
            if 1 <= a <= 12 and 72 <= b <= 84:
                readings.append((a, 1900 + b))
            if 1 <= b <= 12 and 72 <= a <= 84:
                readings.append((b, 1900 + a))
            if len(readings) == 1:
                result.format = "us_legacy_straight_year"
                result.production_month, result.production_year = readings[0]
                result.confidence = 0.5
                result.valid = True
                result.status = "valid"
                result.warnings.append(
                    "Pre-1984 straight-year format: production date decoded; model year is not encoded"
                )
                return result

    result.status = "unrecognised"
    result.warnings.append(
        "The date characters do not match a recognised HIN format; enter the boat details manually"
    )
    return result


async def decode(db: AsyncSession, raw: str, today: date | None = None) -> HinDecode:
    """Decode and, when the MIC is recorded against one manufacturer, name it."""
    result = decode_structure(raw, today)
    if result.mic is None:
        return result
    makers = list(
        (await db.execute(select(Manufacturer).where(Manufacturer.mic_codes.contains([result.mic])))).scalars()
    )
    if len(makers) == 1:
        maker = makers[0]
        result.manufacturer = {"id": str(maker.id), "name": maker.name, "is_synthetic": maker.is_synthetic}
        if maker.is_synthetic:
            result.warnings.append("Manufacturer code belongs to a synthetic test fixture")
    elif len(makers) > 1:
        result.warnings.append("Manufacturer code is recorded against more than one manufacturer; not identified")
    else:
        result.warnings.append(
            f"Manufacturer code {result.mic} is not in the Helm boat database; manufacturer not identified"
        )
    return result
