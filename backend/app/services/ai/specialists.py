"""Domain specialists: one shared, parameterised mechanism (no per-brand agents).

Each specialist is a registry entry — display name, description, routing keywords and
a prompt addendum — over its own ``agent_domain`` corpus. The First Mate consults
specialists by searching their corpus; it never hands control to another agent.
Routing is deterministic keyword matching; in OpenAI mode the model may also choose
domains through the ``search_knowledge`` tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Specialist:
    key: str
    name: str
    description: str
    keywords: tuple[str, ...]
    prompt_addendum: str


SPECIALISTS: dict[str, Specialist] = {
    s.key: s
    for s in (
        Specialist(
            "engine",
            "Engine & Propulsion Pro",
            "Outboard and inboard engines, servicing, fuel systems, cooling and propellers.",
            (
                "engine",
                "outboard",
                "inboard",
                "motor",
                "spark",
                "plug",
                "plugs",
                "impeller",
                "oil",
                "fuel",
                "filter",
                "service",
                "servicing",
                "maintenance",
                "overheating",
                "overheat",
                "starting",
                "start",
                "stall",
                "stalls",
                "idle",
                "propeller",
                "prop",
                "gearbox",
                "lower unit",
                "gear oil",
                "anode",
                "thermostat",
                "water pump",
                "hours",
                "rpm",
                "tell-tale",
                "telltale",
                "carburettor",
                "injector",
            ),
            "Engine questions depend on the exact engine make, model and year. Quote service "
            "intervals and part codes only from cited passages for the vessel's engine.",
        ),
        Specialist(
            "electrical",
            "Electrical & Solar Sage",
            "12V/24V systems, batteries, charging, solar, wiring and lighting.",
            (
                "battery",
                "batteries",
                "electrical",
                "wiring",
                "wire",
                "fuse",
                "solar",
                "charger",
                "charging",
                "inverter",
                "12v",
                "24v",
                "volt",
                "voltage",
                "isolator",
                "switch panel",
                "lights",
                "led",
                "alternator",
            ),
            "Electrical advice must not replace a qualified marine electrician for mains or "
            "high-current work; say so when relevant.",
        ),
        Specialist(
            "plumbing",
            "Pumps & Plumbing Pro",
            "Bilge pumps, freshwater and sanitation systems, hoses and fittings.",
            (
                "bilge",
                "pump",
                "plumbing",
                "hose",
                "toilet",
                "head",
                "sanitation",
                "freshwater",
                "fresh water",
                "tank",
                "through-hull",
                "skin fitting",
                "seacock",
                "float switch",
            ),
            "Distinguish bilge, freshwater and raw-water systems; ask which one when unclear.",
        ),
        Specialist(
            "galley",
            "Galley Guru",
            "Stoves, fridges, gas systems and watermakers.",
            (
                "galley",
                "stove",
                "cooker",
                "fridge",
                "refrigerator",
                "gas",
                "lpg",
                "bbq",
                "watermaker",
                "oven",
                "sink",
            ),
            "Gas installations are safety-critical; never give installation sign-off advice.",
        ),
        Specialist(
            "game_fishing",
            "Game Fishing Guide",
            "Big-game rods, reels, lures, rigging and technique.",
            (
                "marlin",
                "tuna",
                "game fishing",
                "gamefishing",
                "lure",
                "lures",
                "outrigger",
                "teaser",
                "kingfish",
                "swordfish",
                "trolling",
                "igfa",
            ),
            "Fishing regulations change; only state rules that a cited passage supports.",
        ),
        Specialist(
            "anchoring",
            "Anchoring & Mooring Master",
            "Anchors, chain, rode, windlasses and mooring.",
            ("anchor", "anchoring", "chain", "rode", "windlass", "mooring", "shackle", "swivel"),
            "Anchor and chain sizing depends on vessel length and displacement; ask for them.",
        ),
        Specialist(
            "safety",
            "Safety & Compliance Officer",
            "Lifejackets, EPIRBs, flares, fire extinguishers and voyage safety checks.",
            (
                "safety",
                "lifejacket",
                "lifejackets",
                "life jacket",
                "pfd",
                "epirb",
                "plb",
                "flare",
                "flares",
                "fire extinguisher",
                "extinguisher",
                "first aid",
                "checklist",
                "distress",
                "man overboard",
                "liferaft",
                "life raft",
                "emergency",
            ),
            "Never assert a legal or regulatory requirement unless a cited admitted passage "
            "states it; direct users to the official regulator for authoritative rules.",
        ),
        Specialist(
            "rigging",
            "Rigging & Deck Specialist",
            "Sails, lines, blocks, winches and deck hardware.",
            (
                "rigging",
                "sail",
                "sails",
                "halyard",
                "sheet",
                "block",
                "winch",
                "furler",
                "furling",
                "mast",
                "boom",
                "stay",
                "shroud",
                "cleat",
                "deck",
            ),
            "Rigging loads are safety-critical; recommend a professional rigger for inspection.",
        ),
        Specialist(
            "electronics",
            "Electronics & Navigation Expert",
            "Chartplotters, VHF, AIS, radar, sonar and autopilots.",
            (
                "chartplotter",
                "plotter",
                "gps",
                "vhf",
                "radio",
                "ais",
                "radar",
                "sonar",
                "fishfinder",
                "fish finder",
                "transducer",
                "autopilot",
                "nmea",
                "navigation",
            ),
            "Network and transducer compatibility depends on exact models; ask for them.",
        ),
        Specialist(
            "trailer",
            "Trailer & Towing Advisor",
            "Boat trailers, bearings, brakes, winches and towing.",
            (
                "trailer",
                "towing",
                "tow",
                "bearing",
                "bearings",
                "hub",
                "rollers",
                "bunk",
                "bunks",
                "trailer winch",
                "coupling",
                "wof",
            ),
            "Towing limits depend on the tow vehicle and trailer plate; ask for them.",
        ),
        Specialist(
            "fishing",
            "Soft Bait & Inshore Specialist",
            "Inshore fishing tackle, soft baits, knots and species.",
            (
                "fishing",
                "snapper",
                "soft bait",
                "softbait",
                "jig",
                "jigging",
                "knot",
                "rod",
                "reel",
                "hook",
                "sinker",
                "bait",
                "tackle",
                "braid",
                "leader",
            ),
            "Bag and size limits change; only state rules that a cited passage supports.",
        ),
        Specialist(
            "boat_oem",
            "Boat OEM Specialist",
            "Factory specifications and fitted equipment for boat makes and models.",
            (
                "oem",
                "factory",
                "hull",
                "specification",
                "specifications",
                "specs",
                "fitted",
                "standard equipment",
                "model year",
                "hin",
            ),
            "Factory data may be incomplete; say when equipment details are unverified.",
        ),
    )
}


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])")


_PATTERNS = {
    key: [(kw, _keyword_pattern(kw)) for kw in spec.keywords] for key, spec in SPECIALISTS.items()
}


def route(message: str, limit: int = 2) -> list[str]:
    """Deterministically pick up to ``limit`` specialist domains for a message.

    Score = number of distinct keyword hits (multi-word phrases count double).
    Ties break on registry order, so routing is stable.
    """
    text = message.lower()
    scores: list[tuple[int, int, str]] = []
    for order, (key, patterns) in enumerate(_PATTERNS.items()):
        score = sum(2 if " " in kw else 1 for kw, pattern in patterns if pattern.search(text))
        if score:
            scores.append((-score, order, key))
    return [key for _, _, key in sorted(scores)[:limit]]


def public_list() -> list[dict]:
    return [
        {"key": s.key, "name": s.name, "description": s.description} for s in SPECIALISTS.values()
    ]
