"""Deterministic evidence guidance: the next useful, safe request for a job (spec §5.1–5.2).

This is NOT a model. It reads the job's own context (affected system/equipment and
description keywords, the vessel snapshot), the requests that already exist and their
states, and the uploaded assets that are ``available``; then proposes the first missing
step of a fixed, reviewed plan per equipment profile, with a plain "why this matters".

Safety (§5.2): every prompt is a request to look or photograph from where the owner can
already be — never to disconnect, remove guards/covers, open energized equipment, start
or run machinery, or disturb fuel/gas/pressurised/hot systems. :func:`is_safe_wording`
is the blocklist the tests run over every generated prompt; it is also applied at run
time (owner-supplied component names are replaced if they would make a prompt unsafe)
and to contractor/owner-written requests. A request that would need hazardous access is
answered with "I cannot safely get this", which records a visible gap and flags
technician inspection; the plan then skips close-range steps for that component.
There is no photo count: completion is "every relevant step answered, unavailable or waived".
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

CATEGORY_ORDER = (
    "overview",
    "access_route",
    "label",
    "close_up",
    "connections",
    "route",
    "markings",
    "measurement",
    "document",
)
# Steps that need the owner close to the component; skipped once the area is unsafe/inaccessible.
JOB_LEVEL = frozenset({"overview", "access_route", "document"})
CLOSE_RANGE = frozenset({"close_up", "connections", "route", "markings", "measurement"})
DONE_STATES = frozenset({"answered", "unavailable", "waived"})

OPTIONS = ("take_photo", "upload_file", "answer_with_note", "cannot_safely_get")
CANNOT_SAFELY_GET_LABEL = "I cannot safely get this"
SAFETY_NOTE = (
    "Only do this from where you can comfortably stand or kneel, and leave everything as it is. "
    "If getting it would mean going near anything hot, electrical, fuel, gas or moving, choose "
    f"“{CANNOT_SAFELY_GET_LABEL}” — your contractor will look at it on site."
)

# §5.2 blocklist: instructions the product must never give to satisfy a capture request.
_BLOCKLIST = [
    r"\bdisconnect",
    r"\bunplug",
    r"\bremove\b",
    r"\btake (off|out|apart)\b",
    r"\bunscrew",
    r"\bunbolt",
    r"\bloosen",
    r"\bundo\b",
    r"\bdismantl",
    r"\bpry\b",
    r"\bprise\b",
    r"\bopen\b[^.?!]*\b(switchboard|distribution|electrical|panel|cover|casing|housing|junction|fuse ?box|"
    r"breaker|battery box|fuel|gas|tank|cap|valve|filter|cylinder|regulator|engine|hatch over)\b",
    r"\b(start|run|crank|fire up|turn on|switch on|power up|energi[sz]e)\b[^.?!]*"
    r"\b(engine|motor|pump|generator|machinery|outboard|winch|windlass|propeller|it)\b",
    r"\b(while|when)\b[^.?!]*\b(running|turning|spinning|operating|switched on|powered|live)\b",
    r"\bapproach\b",
    r"\btouch\b",
    r"\bhold\b[^.?!]*\b(wire|terminal|cable|hose|pipe)\b",
    r"\breach (in|into|behind|past|under|around)\b",
    r"\bclimb\b",
    r"\bcrawl\b",
    r"\blive (wire|terminal|circuit|cable)",
    r"\benergi[sz]ed\b",
    r"\bprobe\b",
    r"\bmultimeter\b",
    r"\bbleed\b",
    r"\bdrain\b",
    r"\bvent\b",
    r"\bdepressuri",
    r"\brelease\b[^.?!]*\bpressure",
    r"\bpressuri[sz]e",
    r"\bignit",
    r"\bsmell\b[^.?!]*\b(fuel|gas)\b",
    r"\bbypass\b",
    r"\boverride\b",
    r"\bjump(-| )?start",
    r"\bshort\b",
    r"\bcut\b",
    r"\bpull\b",
    r"\bpush\b",
    r"\bmove the\b",
    r"\bmove it\b",
    r"\blift\b",
    r"\bpress\b",
    r"\bsqueeze\b",
    r"\bflex\b",
    r"\bwiggle\b",
    r"\bshake\b",
    r"\btest\b",
    r"\breproduce\b",
]
_BLOCK_RE = [re.compile(p, re.IGNORECASE) for p in _BLOCKLIST]


def unsafe_phrases(text: str) -> list[str]:
    """Blocklisted instruction fragments found in ``text`` (empty when the wording is safe)."""
    return [m.group(0) for rx in _BLOCK_RE if (m := rx.search(text or ""))]


def is_safe_wording(text: str) -> bool:
    return not unsafe_phrases(text)


@dataclass(frozen=True)
class Step:
    category: str
    prompt: str  # "{c}" is the component
    reason: str
    priority: str = "normal"
    measurement_dimension: str | None = None


@dataclass(frozen=True)
class Proposal:
    key: str
    category: str
    component: str | None
    prompt: str
    reason: str
    priority: str
    measurement_dimension: str | None
    safety_note: str = SAFETY_NOTE
    options: tuple[str, ...] = OPTIONS


_OVERVIEW = Step(
    "overview",
    "Can you take a wide photo that shows where the {c} is on the boat? Step back far enough to see the "
    "locker or compartment around it.",
    "A wide view tells the contractor where to go and what they will be working around, before they arrive.",
    "high",
)
_ACCESS = Step(
    "access_route",
    "Show the way in to the {c}: the locker opening, hatch or panel you look through, photographed from a step "
    "back. Leave it as it is.",
    "Working space and obstructions decide which tools and how much time the job needs.",
)
_LABEL = Step(
    "label",
    "Is there a label or model plate on the {c} that you can see without moving anything? If so, photograph it "
    "straight on. If you cannot read it, say so — please do not guess the text.",
    "The exact make and model lets the contractor bring the right parts; we never fill in text we cannot see.",
    "high",
)
_DOCUMENT = Step(
    "document",
    "Do you have a manual, a previous service record or a quote for the {c}? Upload it, or note what you know.",
    "Earlier work and the manufacturer's details save diagnosis time and avoid ordering the wrong part.",
    "low",
)

PROFILES: dict[str, tuple[tuple[str, ...], str, tuple[Step, ...]]] = {
    # name: (keywords, default component, plan)
    "pump": (
        ("pump", "pressure set", "water system"),
        "pump",
        (
            _OVERVIEW,
            _ACCESS,
            _LABEL,
            Step(
                "close_up",
                "Photograph where you see water or wear near the {c}, from where you normally look at it. "
                "Leave the {c} switched off.",
                "Where the water appears narrows down which connection or seal is involved.",
                "high",
            ),
            Step(
                "connections",
                "Photograph each hose or pipe connection on the {c} that you can see as it is, including both "
                "ends of any hose you can follow. If an end is out of sight, mark it inaccessible.",
                "Connection type and condition decide which fittings and clamps the contractor brings.",
            ),
            Step(
                "markings",
                "Photograph any printing on the hoses near the {c} (size, type or standard), close enough to read.",
                "Printed markings are the most reliable clue to hose size and type; we record them as text seen, "
                "not as a measured size.",
            ),
            Step(
                "measurement",
                "If you can reach a hose by the {c} without moving it, wrap a tape measure or a piece of string "
                "around the outside and note the distance around it, and say which you used.",
                "An outside measurement helps the contractor narrow the hose and clamp sizes. It is recorded as "
                "your measurement, not a confirmed size.",
                "normal",
                "hose_external_diameter",
            ),
            _DOCUMENT,
        ),
    ),
    "hose": (
        ("hose", "pipe", "plumbing", "leak", "drip"),
        "hose",
        (
            _OVERVIEW,
            _ACCESS,
            Step(
                "connections",
                "Photograph both ends of the {c} where you can see them as they are. If one end is out of sight, "
                "mark it inaccessible.",
                "Both ends show the fitting types the contractor needs to match.",
                "high",
            ),
            Step(
                "route",
                "Photograph the path the {c} takes, including bends and anything it passes close to.",
                "The route sets the length needed and shows chafe points or tight bends.",
            ),
            Step(
                "markings",
                "Photograph any printing on the {c} (size, type or standard), close enough to read.",
                "Printed markings are the best clue to size and application; they are recorded as text seen.",
            ),
            Step(
                "measurement",
                "If you can reach the {c} without moving it, note the visible length you can follow with a tape "
                "measure, and say where you measured from and to.",
                "A visible length gives a starting allowance; the contractor confirms the final length.",
                "normal",
                "route_length",
            ),
            _DOCUMENT,
        ),
    ),
    "sink": (
        ("sink", "tap", "faucet", "galley", "basin", "shower", "head", "toilet", "sanitation"),
        "sink area",
        (
            _OVERVIEW,
            Step(
                "access_route",
                "Show the cupboard or locker under the {c} with its door open, photographed from a step back.",
                "The space under the {c} decides how the contractor can get to the plumbing.",
            ),
            Step(
                "close_up",
                "Photograph where the water collects under the {c}, from where you normally look.",
                "Where the water collects points to the connection or seal that is leaking.",
                "high",
            ),
            Step(
                "connections",
                "Photograph the visible pipe and hose connections under the {c} as they are.",
                "Connection types decide which fittings, clamps or seals are needed.",
            ),
        ),
    ),
    "engine": (
        ("engine", "outboard", "inboard", "motor", "sterndrive", "diesel", "overheat", "exhaust", "impeller"),
        "engine",
        (
            _OVERVIEW,
            Step(
                "label",
                "With the {c} switched off, photograph its identification plate or sticker if you can see it "
                "without moving covers. If it is not readable, say so — please do not guess.",
                "The plate gives the exact model and serial so parts and procedures match your engine.",
                "high",
            ),
            Step(
                "close_up",
                "With the {c} switched off and cool, photograph the area where you noticed the problem, from where "
                "you normally look at it.",
                "Seeing the symptom area helps the contractor prepare without diagnosing from the photo.",
            ),
            _ACCESS,
            Step(
                "document",
                "Do you have the {c} service record or hours log? Upload it, or note the last service you know of.",
                "Service history shows what was replaced recently and what is due.",
                "normal",
            ),
        ),
    ),
    "electrical": (
        (
            "electrical",
            "electric",
            "battery",
            "batteries",
            "wiring",
            "wire",
            "switch",
            "breaker",
            "fuse",
            "charger",
            "inverter",
            "light",
            "nav light",
            "power",
            "solar",
        ),
        "electrical equipment",
        (
            _OVERVIEW,
            Step(
                "label",
                "Photograph the outside label of the {c} if you can see it without opening anything. If it is not "
                "readable, say so.",
                "The model and rating tell the contractor which replacement or parts to bring.",
                "high",
            ),
            Step(
                "close_up",
                "If you can see marks, discolouration or a warning light on the outside of the {c}, photograph it "
                "from where you are. Keep every cover closed.",
                "Outside signs help the contractor prepare; anything inside a cover is for them to inspect.",
            ),
            _ACCESS,
            Step(
                "document",
                "Do you have a wiring diagram, manual or earlier electrical work record? Upload it or note what "
                "you know.",
                "Existing diagrams and records save tracing time on site.",
                "low",
            ),
        ),
    ),
    "bilge": (
        ("bilge", "float switch"),
        "bilge",
        (
            Step(
                "overview",
                "From the hatch, photograph the {c} area looking down, without going into the space.",
                "The view shows the water level, the pump position and the space the contractor will work in.",
                "high",
            ),
            Step(
                "label",
                "If the bilge pump's label is visible from the hatch, photograph it. If not, mark it not visible.",
                "Pump model and capacity guide the replacement or parts.",
            ),
            Step(
                "route",
                "Photograph where the bilge outlet leaves the hull from outside or from the cockpit, if you can "
                "see it from where you stand.",
                "The outlet route shows hose length and the through-hull fitting involved.",
            ),
            _DOCUMENT,
        ),
    ),
    "fuel_gas": (
        ("fuel", "gas", "lpg", "propane", "petrol", "gasoline", "cooker", "stove"),
        "fuel or gas equipment",
        (
            Step(
                "overview",
                "From a comfortable distance, photograph where the {c} is installed. Leave everything as it is.",
                "Location and surroundings help the contractor plan; fuel and gas work is for them to inspect on site.",
                "high",
            ),
            Step(
                "label",
                "If a label or compliance sticker on the {c} is readable from where you stand, photograph it. "
                "Otherwise mark it not visible.",
                "Labels give the make, model and compliance details the contractor needs.",
            ),
            _DOCUMENT,
        ),
    ),
}
DEFAULT_PLAN: tuple[Step, ...] = (
    _OVERVIEW,
    _ACCESS,
    _LABEL,
    Step(
        "close_up",
        "Photograph the part of the {c} where you notice the problem, from where you normally look at it.",
        "A clear view of the symptom helps the contractor prepare — it is not used to diagnose.",
    ),
    _DOCUMENT,
)

# Caption words that show an unlinked uploaded asset already covers a step.
CAPTION_HINTS = {
    "overview": ("overview", "wide", "location", "where it is"),
    "access_route": ("access", "locker", "hatch", "panel", "opening"),
    "label": ("label", "plate", "sticker", "model", "serial"),
    "close_up": ("close", "leak", "symptom", "damage"),
    "connections": ("connection", "fitting", "clamp", "end"),
    "route": ("route", "run", "path"),
    "markings": ("marking", "printing", "print"),
    "measurement": ("measure", "tape", "size"),
    "document": ("manual", "record", "quote", "invoice", "document"),
}


def norm_component(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _clean_component(value: str | None, fallback: str) -> str:
    c = re.sub(r"\s+", " ", (value or "").strip())[:80]
    if not c or not is_safe_wording(c):
        return fallback
    return c


def matched_profiles(text: str) -> list[str]:
    t = f" {text.lower()} "
    hits: list[tuple[int, str]] = []
    for name, (keywords, _component, _plan) in PROFILES.items():
        positions = [m.start() for kw in keywords if (m := re.search(rf"\b{re.escape(kw)}", t))]
        if positions:
            hits.append((min(positions), name))
    return [name for _pos, name in sorted(hits)]


@dataclass(frozen=True)
class ExistingRequest:
    category: str
    component: str | None
    status: str
    unavailable_reason: str | None = None


def build_plan(
    *,
    affected_system: str | None,
    affected_equipment: str | None,
    title: str,
    issue_description: str,
    occurs_when: str | None = None,
) -> list[tuple[str, Step]]:
    """The ordered (component, step) plan for this job's context."""
    # The named equipment leads; then what the owner described; the broad system name last.
    primary_profiles = matched_profiles(affected_equipment or "")[:1]
    other_text = " ".join(filter(None, [title, issue_description, occurs_when, affected_system]))
    secondary = [p for p in matched_profiles(other_text) if p not in primary_profiles]
    profiles = (primary_profiles + secondary)[:2]
    plan: list[tuple[str, Step]] = []
    if not profiles:
        component = _clean_component(affected_equipment or affected_system, "affected equipment")
        return [(component, s) for s in DEFAULT_PLAN]
    for i, name in enumerate(profiles):
        _keywords, default_component, steps = PROFILES[name]
        primary = i == 0 and name in primary_profiles
        component = _clean_component(affected_equipment, default_component) if primary else default_component
        for step in steps:
            if any(s.category == step.category and norm_component(c) == norm_component(component) for c, s in plan):
                continue
            # One overview / access route / document for the job is enough when profiles overlap.
            if step.category in JOB_LEVEL and any(s.category == step.category for _c, s in plan):
                continue
            plan.append((component, step))
    return plan


def _key(category: str, component: str) -> str:
    return f"{category}:{norm_component(component)}"


def next_proposal(
    *,
    affected_system: str | None,
    affected_equipment: str | None,
    title: str,
    issue_description: str,
    occurs_when: str | None,
    vessel_context: dict | None,
    existing: Iterable[ExistingRequest],
    asset_captions: Iterable[str] = (),
    asset_request_categories: Iterable[str] = (),
) -> Proposal | None:
    """First plan step not yet covered by a request (any state) or an available asset; None when done."""
    existing = list(existing)
    covered = {_key(r.category, r.component or "") for r in existing}
    covered_any_component = {r.category for r in existing if r.status in DONE_STATES or r.status == "outstanding"}
    unsafe_components = {
        norm_component(r.component)
        for r in existing
        if r.status == "unavailable" and r.unavailable_reason == "cannot_safely_access"
    }
    captions = [c.lower() for c in asset_captions if c]
    asset_categories = set(asset_request_categories)
    plan = build_plan(
        affected_system=affected_system,
        affected_equipment=affected_equipment,
        title=title,
        issue_description=issue_description,
        occurs_when=occurs_when,
    )
    for component, step in plan:
        key = _key(step.category, component)
        if key in covered:
            continue
        if step.category in JOB_LEVEL and step.category in covered_any_component:
            continue  # one job-level view of these is enough
        if step.category in asset_categories:
            continue
        if any(h in cap for cap in captions for h in CAPTION_HINTS.get(step.category, ())):
            continue
        if step.category in CLOSE_RANGE and (
            norm_component(component) in unsafe_components or norm_component(None) in unsafe_components
        ):
            continue  # the area cannot be reached safely: leave it to the technician
        prompt = step.prompt.format(c=component)
        reason = _reason(step, component, vessel_context)
        if not (is_safe_wording(prompt) and is_safe_wording(reason)):
            prompt = step.prompt.format(c="affected equipment")
            if not is_safe_wording(prompt):  # pragma: no cover - templates are tested safe
                continue
        return Proposal(
            key=key,
            category=step.category,
            component=component,
            prompt=prompt,
            reason=reason,
            priority=step.priority,
            measurement_dimension=step.measurement_dimension,
        )
    return None


def _reason(step: Step, component: str, vessel_context: dict | None) -> str:
    reason = step.reason.format(c=component)
    if step.category == "label" and vessel_context:
        engine = vessel_context.get("engine") or {}
        if "engine" in component.lower() and engine.get("make"):
            known = " ".join(str(v) for v in (engine.get("make"), engine.get("model")) if v)
            reason += f" Your boat record lists {known}; the plate confirms it."
    return reason


def proposal_by_key(key: str, **context) -> Proposal | None:
    """Re-derive the current proposal and check it is the one the client saw."""
    p = next_proposal(**context)
    return p if p is not None and p.key == key else None
