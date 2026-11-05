"""HIN / CIN decoding and the vessel save hook (suggestions only, never overwrites)."""

from datetime import date

import pytest

from app.config import get_settings
from app.database import async_session
from app.models.boat_db import Manufacturer
from app.services.hin import decode_structure
from app.tests.test_catalogue_support import API, make_boat

TODAY = date(2026, 11, 5)


@pytest.mark.parametrize(
    "raw, fmt, mic, serial, month, prod_year, model_year",
    [
        ("ABC12345D404", "us_current", "ABC", "12345", 4, 2004, 2004),
        ("abc-12345-h2 03", "us_current", "ABC", "12345", 8, 2002, 2003),  # built Aug 2002 for MY 2003
        ("NZ-XYZ4A7B9L526", "iso_10087", "XYZ", "4A7B9", 12, 2025, 2026),
        ("ABC12345A999", "us_current", "ABC", "12345", 1, 1999, 1999),
        ("ABC12345M79J", "us_legacy_model_year", "ABC", "12345", 10, None, 1979),
        ("ABC123450779", "us_legacy_straight_year", "ABC", "12345", 7, 1979, None),
        ("ABC123457907", "us_legacy_straight_year", "ABC", "12345", 7, 1979, None),
    ],
)
def test_decode_formats(raw, fmt, mic, serial, month, prod_year, model_year):
    r = decode_structure(raw, TODAY)
    assert r.valid and r.status == "valid", r.warnings
    assert (r.format, r.mic, r.serial, r.production_month, r.production_year, r.model_year) == (
        fmt,
        mic,
        serial,
        month,
        prod_year,
        model_year,
    )
    assert r.manufacturer is None  # structural decode never names a manufacturer


def test_normalisation_and_country():
    r = decode_structure(" nz-abc12345d404 ", TODAY)
    assert r.normalized == "NZ-ABC12345D404" and r.country_code == "NZ"
    assert decode_structure("ABC 12345 D4 04", TODAY).normalized == "ABC12345D404"


@pytest.mark.parametrize("raw", ["", "ABC123", "ABC12345D4045", "ABC12345O404", "ABC1234$D404", "12ABC12345D404"])
def test_invalid(raw):
    r = decode_structure(raw, TODAY)
    assert not r.valid and r.status == "invalid" and r.warnings
    assert r.model_year is None and r.production_year is None


@pytest.mark.parametrize("raw", ["ABC12345D450", "ABC123450505", "ABC123459999", "ABC12345Z404", "NZ-ABC12345M79J"])
def test_unrecognised_or_ambiguous_dates_are_null(raw):
    r = decode_structure(raw, TODAY)
    assert r.status == "unrecognised" and not r.valid
    assert r.model_year is None and r.production_year is None and r.production_month is None
    assert r.warnings


def test_inconsistent_production_digit_is_not_guessed():
    r = decode_structure("ABC12345D704", TODAY)  # year digit 7 cannot belong to model year 2004
    assert r.valid and r.model_year == 2004 and r.production_year is None
    assert r.confidence < 0.9 and any("inconsistent" in w for w in r.warnings)
    future = decode_structure("ABC12345L627", TODAY)  # Dec 2026 production, not yet happened
    assert future.model_year == 2027 and future.production_year is None


async def test_endpoint_manufacturer_only_when_mic_recorded(client, monkeypatch):
    r = await client.post(f"{API}/boat-db/hin/decode", json={"hin": "Z9X12345D404"})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] and body["manufacturer"] is None
    assert any("not in the Helm boat database" in w for w in body["warnings"])

    await make_boat("Synthetic Fixture Boats", "Fixture 600", 2004, mic_codes=["Z9X"], is_synthetic=True)
    body = (await client.post(f"{API}/boat-db/hin/decode", json={"hin": "Z9X12345D404"})).json()
    assert body["manufacturer"]["name"] == "Synthetic Fixture Boats" and body["manufacturer"]["is_synthetic"]

    async with async_session() as s:  # duplicated MIC → ambiguous → not identified
        s.add(Manufacturer(name="Another", mic_codes=["Z9X"]))
        await s.commit()
    body = (await client.post(f"{API}/boat-db/hin/decode", json={"hin": "Z9X12345D404"})).json()
    assert body["manufacturer"] is None and any("more than one" in w for w in body["warnings"])

    assert (await client.post(f"{API}/boat-db/hin/decode", json={"hin": "x", "extra": 1})).status_code == 422
    monkeypatch.setattr(get_settings(), "rate_limit_hin_per_minute", 2)
    codes = [
        (await client.post(f"{API}/boat-db/hin/decode", json={"hin": "ABC12345D404"})).status_code for _ in range(3)
    ]
    assert codes[-1] == 429


VESSEL = {
    "nickname": "Fixture",
    "make": "stabicraft",
    "model": "2050-SUPERCAB",
    "year": 2022,
    "propulsion_type": "outboard",
}


async def test_vessel_hook_stores_suggestion_only_and_links_model_year(client, customer):
    boat = await make_boat("Stabicraft", "2050 Supercab", 2022, mic_codes=["Z9Y"], is_synthetic=True)
    # HIN says model year 2019 and a different maker exists for the MIC; owner's details win.
    r = await client.post(f"{API}/vessels/", json={**VESSEL, "hin": "z9y-12345-a9-19"}, headers=customer.headers)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["hin"] == "Z9Y12345A919" and v["hin_status"] == "valid"
    assert v["hin_decoded"]["model_year"] == 2019 and v["hin_decoded"]["manufacturer"]["name"] == "Stabicraft"
    assert "Suggestion" in v["hin_decoded"]["note"]
    assert (v["make"], v["model"], v["year"]) == ("stabicraft", "2050-SUPERCAB", 2022)  # never overwritten
    assert v["model_year_id"] == str(boat["model_year_id"])  # normalised exact make/model/year match

    vid = v["id"]
    r = await client.patch(f"{API}/vessels/{vid}", json={"hin": "NOT-A-HIN"}, headers=customer.headers)
    assert r.json()["hin_status"] == "invalid" and r.json()["hin_decoded"]["valid"] is False
    r = await client.patch(f"{API}/vessels/{vid}", json={"hin": "ABC123459999"}, headers=customer.headers)
    assert r.json()["hin_status"] == "unrecognised"
    r = await client.patch(f"{API}/vessels/{vid}", json={"hin": None}, headers=customer.headers)
    assert r.json()["hin"] is None and r.json()["hin_status"] is None and r.json()["hin_decoded"] is None

    r = await client.patch(f"{API}/vessels/{vid}", json={"year": 2023}, headers=customer.headers)
    assert r.json()["model_year_id"] is None  # no longer an exact match
    r = await client.patch(f"{API}/vessels/{vid}", json={"year": 2022}, headers=customer.headers)
    assert r.json()["model_year_id"] == str(boat["model_year_id"])
