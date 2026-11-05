"""Server-side grounding guard applied to every First Mate answer (both providers).

* Citations ``[n]`` survive only when ``n`` is a passage retrieved in this turn.
* ``grounded``              — at least one valid citation and no conflicting evidence.
* ``conflicting``           — admitted, applicable passages retrieved in this turn declare
                              different values for the same fact key (with overlapping
                              applicability scopes).
* ``insufficient_evidence`` — no valid citation.

When the status is not ``grounded`` the reply may not assert part numbers,
compatibility guarantees or safety/regulatory claims: such sentences are removed and
an explanation plus a relevant clarifying question is appended. Cart proposals are
withdrawn. In a grounded answer part numbers must come from retrieved passages or
product tool results, a product may be described as fitting only when its central
fitment status is ``verified_fit``/``universal``, and uncited safety/regulatory
claims are removed. Instruction-like text (prompt injection echoes) is always removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.ai.tools import ProductRef, TurnRuntime
from app.services.fitment import VesselProfile, norm
from app.services.rag.retrieval import RetrievedChunk

CITATION = re.compile(r"\[(\d{1,3})\]")
# Hyphenated codes with a digit (SYN-PLUG-150, 6AW-12345-00) or long upper-case
# alphanumerics with digits (BR6HS10, LFR6A12).
_CODE = re.compile(r"\b(?:[A-Z0-9]{1,12}(?:-[A-Z0-9]{1,12}){1,5}|[A-Z0-9]{5,20})\b")
FIT_CLAIM = re.compile(
    r"\b(fits?|fitting|fitted|compatible|compatibility|suits?|suitable|right part|correct part|"
    r"will work (?:with|on)|guarantee[ds]?)\b",
    re.IGNORECASE,
)
_FIT_NEGATION = re.compile(
    r"\b(unknown|not (?:verified|confirmed|known)|cannot|can't|can not|unable|unconfirmed|"
    r"does not fit|doesn't fit|not fit|no verified)\b",
    re.IGNORECASE,
)
SAFETY_CLAIM = re.compile(
    r"\b(required by law|legal(?:ly)? requir\w*|law requires|regulations? (?:require|state|say)\w*|"
    r"mandatory|compulsory|must (?:legally )?carry|is (?:il)?legal|compliant|compliance|"
    r"certified|approved by|maritime nz (?:requires|rules|says))\b",
    re.IGNORECASE,
)
INJECTION = re.compile(
    r"(ignore\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|other)\s+"
    r"(?:instructions|rules|prompts?)|disregard\s+(?:all\s+|any\s+|the\s+|your\s+)?"
    r"(?:previous|prior|above|earlier|instructions|rules)|system\s+prompt|you\s+are\s+now|"
    r"new\s+instructions|developer\s+mode|jailbreak|(?:^|\s)(?:system|assistant|developer)\s*:|"
    r"tell\s+the\s+(?:user|customer)\s+that|add\s+.{0,60}\bto\s+(?:the|their|his|her)\s+cart)",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class GuardResult:
    content: str
    status: str
    note: str
    cited_refs: list[int]
    citations: list[dict]
    products: list[dict]
    actions: list[dict]
    conflicts: dict[str, list[str]] = field(default_factory=dict)


def is_instruction_like(text: str) -> bool:
    return bool(INJECTION.search(text))


def _is_code(token: str) -> bool:
    return any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token)


def _codes(text: str) -> set[str]:
    return {m.group(0).upper() for m in _CODE.finditer(text) if _is_code(m.group(0))}


def _overlap(a: dict, b: dict) -> bool:
    """Two applicability scopes overlap unless some key restricts both to disjoint values."""
    for key in set(a) & set(b):
        va = {norm(str(v)) for v in (a[key] if isinstance(a[key], list) else [a[key]])}
        vb = {norm(str(v)) for v in (b[key] if isinstance(b[key], list) else [b[key]])}
        if not va & vb:
            return False
    return True


def detect_conflicts(
    chunks: list[tuple[int, RetrievedChunk]],
) -> tuple[dict[str, list[str]], set[int]]:
    """Return ({fact_key: [distinct values]}, refs involved) for conflicting facts."""
    by_key: dict[str, list[tuple[str, str, int, RetrievedChunk]]] = {}
    for ref, chunk in chunks:
        for fact in chunk.facts:
            key = str(fact.get("key", "")).strip().lower()
            value = str(fact.get("value", "")).strip()
            if key and value:
                by_key.setdefault(key, []).append((norm(value), value, ref, chunk))
    conflicts: dict[str, list[str]] = {}
    refs: set[int] = set()
    for key, entries in by_key.items():
        for i, (nv_a, va, ra, ca) in enumerate(entries):
            for nv_b, vb, rb, cb in entries[i + 1 :]:
                if (
                    nv_a != nv_b
                    and ca.source_id != cb.source_id
                    and _overlap(ca.applies_to, cb.applies_to)
                ):
                    values = conflicts.setdefault(key, [])
                    for v in (va, vb):
                        if v not in values:
                            values.append(v)
                    refs.update({ra, rb})
    return conflicts, refs


def _split(text: str) -> list[list[str]]:
    return [_SENTENCE.split(line) for line in text.split("\n")]


def _join(lines: list[list[str]]) -> str:
    out = []
    for sentences in lines:
        line = " ".join(s for s in sentences if s.strip())
        if re.fullmatch(r"\s*(?:[-*•]|\d+[.)])?\s*", line):
            continue
        out.append(line)
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _filter(text: str, keep) -> str:
    return _join([[s for s in sentences if keep(s)] for sentences in _split(text)])


def _vessel_tokens(profile: VesselProfile | None) -> set[str]:
    if profile is None:
        return set()
    values = [
        profile.make,
        profile.model,
        *(f.model or "" for f in profile.facts),
        *(f.make for f in profile.facts),
    ]
    tokens: set[str] = set()
    for value in values:
        tokens |= _codes(value or "")
        tokens |= {t.upper() for t in re.findall(r"[A-Za-z0-9-]+", value or "")}
    return tokens


def _fact_label(key: str) -> str:
    return key.replace("_", " ")


def _clarifying_question(profile: VesselProfile | None, conflicts: dict[str, list[str]]) -> str:
    if profile is None:
        return (
            "Which boat and engine is this for? If you add your vessel in My Vessel I can check "
            "sources and fitment for it."
        )
    if not profile.engines:
        return (
            f"What engine (make, model and year) does {profile.nickname} have? Adding it to My "
            "Vessel lets me check sources and fitment."
        )
    if conflicts:
        return (
            "Could you confirm your engine's exact model, year and serial number (or check with "
            "an authorised dealer) so I can narrow this down?"
        )
    return (
        "Could you tell me a bit more — which system or component this is about, the symptom you're "
        "seeing, or the exact model of the part?"
    )


def _citation(ref: int, chunk: RetrievedChunk) -> dict:
    excerpt = chunk.content if len(chunk.content) <= 300 else chunk.content[:297].rstrip() + "…"
    return {
        "index": ref,
        "source_id": str(chunk.source_id),
        "chunk_id": str(chunk.chunk_id),
        "title": chunk.title,
        "publisher": chunk.publisher,
        "url": chunk.url,
        "licence": chunk.licence,
        "excerpt": excerpt,
        "is_synthetic": chunk.is_synthetic,
    }


def _fix_fit_claims(sentence: str, refs: list[ProductRef]) -> str:
    if not FIT_CLAIM.search(sentence) or _FIT_NEGATION.search(sentence):
        return sentence
    lowered = sentence.lower()
    for ref in refs:
        if ref.positive:
            continue
        p = ref.product
        if p.name.lower() in lowered or p.sku.lower() in lowered:
            label = (
                "fit is unknown" if ref.fitment.status == "unknown" else "does not fit this vessel"
            )
            return f"{p.name}: {label} — {ref.fitment.message}."
    return sentence


def apply_guard(
    content: str, runtime: TurnRuntime, profile: VesselProfile | None, max_products: int = 5
) -> GuardResult:
    retrieved = runtime.retrieved
    text = content or ""

    # 1. Instruction-like text never survives, whatever its origin.
    text = _filter(text, lambda s: not is_instruction_like(s))

    # 2. Only citations of passages retrieved in this turn survive.
    text = CITATION.sub(lambda m: m.group(0) if int(m.group(1)) in retrieved else "", text)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)

    conflicts, conflict_refs = detect_conflicts(sorted(retrieved.items()))
    conflict_values = {norm(v) for values in conflicts.values() for v in values}
    vessel_tokens = _vessel_tokens(profile)
    product_refs = list(runtime.products.values())
    allowed_codes = set(vessel_tokens)
    for chunk in retrieved.values():
        allowed_codes |= _codes(chunk.content)
        allowed_codes |= {str(f.get("value", "")).upper() for f in chunk.facts}
    for ref in product_refs:
        allowed_codes.add(ref.product.sku.upper())
        allowed_codes |= {str(n).upper() for n in (ref.product.oem_part_numbers or [])}

    def cited(s: str) -> bool:
        return any(int(n) in retrieved for n in CITATION.findall(s))

    def has_unverified_code(s: str, allowed: set[str]) -> bool:
        return any(code not in allowed for code in _codes(CITATION.sub("", s)))

    status = (
        "conflicting"
        if conflicts
        else (
            "grounded"
            if any(int(n) in retrieved for n in CITATION.findall(text))
            else "insufficient_evidence"
        )
    )

    if status == "grounded":
        product_names = [
            n for r in product_refs for n in (r.product.name.lower(), r.product.sku.lower())
        ]

        def keep(s: str) -> bool:
            if SAFETY_CLAIM.search(s) and not cited(s):
                return False
            # An uncited compatibility claim that names no tool-returned product has no
            # basis (claims naming a product are checked against fitment below).
            if (
                FIT_CLAIM.search(s)
                and not _FIT_NEGATION.search(s)
                and not cited(s)
                and not any(n in s.lower() for n in product_names)
            ):
                return False
            return True

        lines = []
        for sentences in _split(text):
            kept = []
            for s in sentences:
                if not keep(s):
                    continue
                if has_unverified_code(s, allowed_codes):
                    s = _CODE.sub(
                        lambda m: (
                            m.group(0)
                            if (m.group(0).upper() in allowed_codes or not _is_code(m.group(0)))
                            else "[unverified part number removed]"
                        ),
                        s,
                    )
                kept.append(_fix_fit_claims(s, product_refs))
            lines.append(kept)
        text = _join(lines)
        if not any(int(n) in retrieved for n in CITATION.findall(text)):
            status = "insufficient_evidence"

    if status != "grounded":

        def keep_limited(s: str) -> bool:
            plain = CITATION.sub("", s)
            if has_unverified_code(plain, vessel_tokens):
                return False
            if FIT_CLAIM.search(plain) and not _FIT_NEGATION.search(plain):
                return False
            if SAFETY_CLAIM.search(plain):
                return False
            if conflict_values and any(v and v in norm(plain) for v in conflict_values):
                return False
            return True

        text = _filter(text, keep_limited)
        if status == "insufficient_evidence":
            text = CITATION.sub("", text).strip()
            label = profile.label if profile else "your boat"
            limit = (
                f"I couldn't find an admitted source that answers this for {label}, so I won't "
                "guess at part numbers, compatibility or safety requirements."
            )
        else:
            keys = ", ".join(_fact_label(k) for k in conflicts)
            refs = " and ".join(f"[{r}]" for r in sorted(conflict_refs))
            limit = (
                f"The admitted sources I found disagree about the {keys} ({refs}), so I can't "
                "give you a reliable answer on that."
            )
        question = _clarifying_question(profile, conflicts)
        text = "\n\n".join(p for p in (text, limit, question) if p)

    cited_refs = sorted({int(n) for n in CITATION.findall(text) if int(n) in retrieved})
    citations = [_citation(r, retrieved[r]) for r in cited_refs]

    ordered = sorted(product_refs, key=lambda r: (not r.positive, not r.in_stock))[:max_products]
    products = [r.to_response() for r in ordered]
    actions = list(runtime.proposals) if status == "grounded" else []

    if status == "grounded":
        note = f"Based on {len(cited_refs)} admitted source passage(s)."
        if any(retrieved[r].applicability == "unconfirmed" for r in cited_refs):
            note += " Some passages could not be confirmed against your vessel's details."
    elif status == "conflicting":
        note = "Admitted sources conflict on: " + ", ".join(_fact_label(k) for k in conflicts) + "."
    else:
        note = "No admitted source passage supported an answer."
    if any(retrieved[r].is_synthetic for r in cited_refs):
        note += " Cited sources include synthetic test fixtures — not real maintenance, safety or regulatory guidance."
    return GuardResult(text, status, note, cited_refs, citations, products, actions, conflicts)
