"""Server-side grounding guard applied to every First Mate answer (both providers).

The guard never trusts the model's own citations. Every sentence of the draft is
classified clause by clause (decision D21, ``app.services.ai.support``):

* **framing** — clauses made only of framing/clarification vocabulary and the vessel's
  own identifiers (no numbers, no advice/safety/regulatory wording);
* **product statements** — clauses about a product returned by the product tools in
  this turn; compatibility wording must match central fitment (``verified_fit`` /
  ``universal`` to say it fits) and the clause may only add catalogue vocabulary;
* **claims** — everything else. A claim survives only when a passage that the same
  sentence cites (retrieved in this turn, admitted) supports it: same numbers, units
  and identifiers, same polarity, and the claim's content words.

A sentence with any unsupported clause is removed, never certified. Citations stay
only on sentences whose claims they support.

Status:

* ``conflicting``           — admitted, applicable passages retrieved in this turn declare
                              different values for the same fact key (overlapping scopes);
* ``grounded``              — at least one supported claim survives and nothing conflicts;
* ``insufficient_evidence`` — otherwise.

When the status is not ``grounded`` the model's draft is discarded: the reply is a
controlled limitation plus a relevant clarifying question, and cart proposals are
withdrawn. Instruction-like text (prompt-injection echoes) is always removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.ai import support
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
# Advice, obligation, safety or regulatory wording: never mere framing.
ADVICE = re.compile(
    r"\b(must|should|shall|need(?:s|ed)?\s+to|have\s+to|has\s+to|recommend\w*|advis\w*|ensure|"
    r"make\s+sure|always|never|avoid\w*|do\s+not|don'?t|required?|requires|requirement\w*|law|laws|"
    r"legal\w*|illegal|regulat\w*|rules?|safe\w*|unsafe|danger\w*|hazard\w*|warning|caution|"
    r"mandatory|compulsory|permit\w*|allowed|forbidden|prohibit\w*)\b",
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
# "… hours. [1]" → "… hours [1]." so a trailing citation stays with its sentence.
_TRAILING_CITATION = re.compile(r"([.!?])((?:\s*\[\d{1,3}\])+)")
_HEADING = re.compile(r"^\s*(?:#{1,6}\s+(?P<a>.+?)|\*\*(?P<b>.+?)\*\*:?)\s*$")
_MARKDOWN = re.compile(r"[*_`#>]|^\s*(?:[-•]|\d+[.)])\s+")

# Words that frame, clarify or ask — they assert nothing about the boat or the world.
FRAMING_VOCAB = support.content_tokens(
    "here is are what admitted source sources say says said found find passage passages answer "
    "question help hope check checked confirm confirmed apply applies boat vessel selected select "
    "fit information detail details relevant following below above let know like want tell more "
    "about sorry unfortunately note synthetic test fixture fixtures real guidance maintenance "
    "according look looked searched search show shows mention mentions cover covers couldn't "
    "could unable sure narrow down add added adding my exact make model year serial number "
    "engine symptom symptoms seeing component system part type size hull dealer authorised "
    "garage profile record records helm first mate catalogue product products matching store "
    "happy thanks thank great question questions else anything rely relied relying based "
    "manual manuals guide guides document documents documentation handbook notes owner owners "
    "information specific particular which kind sort these those following steps one"
)
# Extra words allowed in a statement about a tool-returned product.
PRODUCT_VOCAB = support.content_tokens(
    "fit fits fitting fitted compatible compatibility suit suits suitable verified verify unknown "
    "match matches matched fitment stock available availability price priced cost costs each nzd "
    "sku code item listed list sell sells sold have we our order buy cart add tap press button "
    "option options alternative choice range brand made by part number"
)


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
    claims: list[dict] = field(default_factory=list)
    removed_statements: int = 0


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
                if nv_a != nv_b and ca.source_id != cb.source_id and _overlap(ca.applies_to, cb.applies_to):
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


def _vessel_tokens(profile: VesselProfile | None) -> set[str]:
    if profile is None:
        return set()
    values = [
        profile.nickname,
        profile.label,
        profile.make,
        profile.model,
        str(profile.year or ""),
        *(f.model or "" for f in profile.facts),
        *(f.make for f in profile.facts),
        *(str(f.year or "") for f in profile.facts),
    ]
    tokens: set[str] = set()
    for value in values:
        tokens |= support.content_tokens(value or "")
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


_FIT_CLAUSE = re.compile(r"[,;:]|\s(?:although|though|but|while|whereas|however|and|or)\s", re.IGNORECASE)
_GENERIC_TOKENS = {
    "synthetic",
    "marine",
    "engine",
    "outboard",
    "spare",
    "kit",
    "pump",
    "plug",
    "plugs",
    "spark",
    "filter",
    "filters",
    "fuel",
    "oil",
    "water",
    "with",
    "for",
    "the",
    "and",
    "pack",
    "set",
    "litre",
    "bilge",
    "impeller",
    "assembly",
    "replacement",
    "part",
    "parts",
    "boat",
}


def _product_tokens(ref: ProductRef) -> set[str]:
    p = ref.product
    tokens = {p.sku.lower()}
    if getattr(p, "brand", None):
        tokens.add(p.brand.lower())
    for tok in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", p.name.lower()):
        if tok not in _GENERIC_TOKENS and (len(tok) >= 4 or any(c.isdigit() for c in tok)):
            tokens.add(tok)
    return tokens


def _mentions(text: str, ref: ProductRef) -> bool:
    lowered = text.lower()
    if ref.product.name.lower() in lowered:
        return True
    words = set(re.findall(r"[a-z0-9][a-z0-9\-]{2,}", lowered))
    return bool(words & _product_tokens(ref))


def _product_identity(ref: ProductRef) -> set[str]:
    """Every token the catalogue itself states about a product (name, codes, price, fitment)."""
    p = ref.product
    response = ref.to_response()
    cents = int(response["effective_price_cents"] or 0)
    texts = [
        p.name,
        p.sku,
        p.brand or "",
        " ".join(str(n) for n in (p.oem_part_numbers or [])),
        ref.fitment.message,
        f"{cents / 100:.2f}",
        str(cents // 100) if cents % 100 == 0 else "",
        str(p.stock_quantity or 0),
    ]
    tokens: set[str] = set()
    for text in texts:
        tokens |= support.content_tokens(text)
    return tokens


def _fix_fit_claims(sentence: str, refs: list[ProductRef]) -> str | None:
    """Enforce central fitment on compatibility claims.

    Each clause is judged separately (a negation elsewhere in the sentence does not
    excuse an affirmative claim). An affirmative fit claim about a product without a
    positive fitment result is replaced by that product's real fitment status; an
    affirmative claim that names no positively-fitted product is dropped (None)."""
    plain = CITATION.sub("", sentence)
    if not FIT_CLAIM.search(plain):
        return sentence
    affirmative = [c for c in _FIT_CLAUSE.split(plain) if FIT_CLAIM.search(c) and not _FIT_NEGATION.search(c)]
    if not affirmative:
        return sentence
    # Products are matched against the whole sentence ("…the X, which fits").
    for ref in refs:
        if not ref.positive and _mentions(plain, ref):
            label = "fit is unknown" if ref.fitment.status == "unknown" else "does not fit this vessel"
            return f"{ref.product.name}: {label} — {ref.fitment.message}."
    # A positive claim must be anchored to a product verified to fit (or universal);
    # product-agnostic claims ("will work with your vessel") are dropped.
    if not any(ref.positive and _mentions(plain, ref) for ref in refs):
        return None
    return sentence


@dataclass
class _Context:
    retrieved: dict[int, RetrievedChunk]
    product_refs: list[ProductRef]
    vessel_tokens: set[str]
    heading_tokens: set[str]
    units: dict[int, list[support.Unit]] = field(default_factory=dict)

    def units_for(self, refs: list[int]) -> list[support.Unit]:
        out: list[support.Unit] = []
        for ref in refs:
            if ref not in self.units:
                chunk = self.retrieved[ref]
                self.units[ref] = support.passage_units(ref, chunk.content, chunk.facts)
            out += self.units[ref]
        return out


def _plain(sentence: str) -> str:
    text = CITATION.sub("", sentence)
    text = _MARKDOWN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _benign(clause: support.Clause, allowed: set[str], *, product: bool) -> bool:
    """Framing (or, in a product statement, catalogue wording) that asserts nothing else."""
    if ADVICE.search(clause.text) or SAFETY_CLAIM.search(clause.text):
        return False
    if not product and FIT_CLAIM.search(clause.text) and not _FIT_NEGATION.search(clause.text):
        return False
    vocab = FRAMING_VOCAB | PRODUCT_VOCAB if product else FRAMING_VOCAB
    return clause.tokens <= (vocab | allowed)


def _judge(sentence: str, ctx: _Context) -> tuple[str | None, dict | None, str]:
    """Return (sentence to keep or None, claim record or None, kind).

    ``kind`` is ``claim`` (passage-supported), ``product`` (checked against the catalogue
    and central fitment) or ``framing``."""
    if is_instruction_like(sentence):
        return None, None, ""
    refs = sorted({int(n) for n in CITATION.findall(sentence) if int(n) in ctx.retrieved})
    plain = _plain(sentence)
    if not plain:
        return None, None, ""

    heading = _HEADING.match(sentence)
    if heading and not refs:
        text = heading.group("a") or heading.group("b") or ""
        if not ADVICE.search(text) and support.content_tokens(text) <= (
            ctx.heading_tokens | ctx.vessel_tokens | FRAMING_VOCAB
        ):
            return sentence, None, "framing"
        return None, None, ""

    mentioned = [r for r in ctx.product_refs if _mentions(plain, r)]
    if mentioned or FIT_CLAIM.search(plain):
        fixed = _fix_fit_claims(sentence, ctx.product_refs)
        if fixed is None:
            return None, None, ""
        if fixed != sentence:
            return fixed, None, "product"  # server-generated fitment statement
    allowed = set(ctx.vessel_tokens)
    for ref in mentioned:
        allowed |= _product_identity(ref)

    units = ctx.units_for(refs)
    evidence: list[support.Unit] = []
    claim_texts: list[str] = []
    body = plain
    lead, colon, rest = plain.partition(":")
    lead_clause = support.Clause(lead, support.content_tokens(lead), set(), False)
    if colon and rest.strip() and _benign(lead_clause, allowed, product=False):
        body = rest  # "Here is what the manual says: …" — judge what follows the framing
    for clause in support.clauses(body):
        # Passage support first, so a cited fact keeps its citation even when it also
        # names a catalogue product; otherwise it must be framing/catalogue wording.
        found = support.support(clause, units) if clause.tokens else support.Support(False)
        if found.supported:
            evidence += found.evidence
            claim_texts.append(clause.text)
        elif not _benign(clause, allowed, product=bool(mentioned)):
            return None, None, ""
    if not evidence:
        # Nothing here needed a passage: citations would overstate what it rests on.
        kind = "product" if mentioned else "framing"
        return re.sub(r"[ \t]+([.,;:!?])", r"\1", CITATION.sub("", sentence)).rstrip(), None, kind
    used = sorted({u.ref for u in evidence})
    kept = CITATION.sub(lambda m: m.group(0) if int(m.group(1)) in used else "", sentence)
    kept = re.sub(r"[ \t]+([.,;:!?])", r"\1", kept)
    claim = {
        "text": plain,
        "refs": used,
        "evidence": [
            {
                "ref": u.ref,
                "passage": u.text,
                "applicability": ctx.retrieved[u.ref].applicability,
                "applies_to": ctx.retrieved[u.ref].applies_to,
            }
            for u in dict.fromkeys(evidence)
        ],
    }
    return kept, claim, "claim"


def apply_guard(
    content: str, runtime: TurnRuntime, profile: VesselProfile | None, max_products: int = 5
) -> GuardResult:
    retrieved = runtime.retrieved
    text = _TRAILING_CITATION.sub(lambda m: f"{m.group(2)}{m.group(1)}", content or "")

    conflicts, conflict_refs = detect_conflicts(sorted(retrieved.items()))
    product_refs = list(runtime.products.values())
    heading_tokens: set[str] = set()
    for chunk in retrieved.values():
        heading_tokens |= support.content_tokens(f"{chunk.title} {chunk.heading or ''}")
        for value in chunk.applies_to.values():
            heading_tokens |= support.content_tokens(" ".join(value) if isinstance(value, list) else str(value))
    ctx = _Context(retrieved, product_refs, _vessel_tokens(profile), heading_tokens)

    claims: list[dict] = []
    removed = 0
    lines: list[list[str]] = []
    product_statements: list[str] = []
    for sentences in _split(text):
        kept_line = []
        for sentence in sentences:
            if not sentence.strip():
                continue
            kept, claim, kind = _judge(sentence, ctx)
            if kept is None:
                removed += 1
                continue
            kept_line.append(kept)
            if claim:
                claims.append(claim)
            if kind == "product":
                product_statements.append(_MARKDOWN.sub("", kept).strip())
        lines.append(kept_line)

    if conflicts:
        status = "conflicting"
    elif claims:
        status = "grounded"
    else:
        status = "insufficient_evidence"

    if status == "grounded":
        text = _join(lines)
    else:
        claims = []
        if status == "insufficient_evidence":
            label = profile.label if profile else "your boat"
            limit = (
                f"I couldn't find an admitted source that answers this for {label}, so I won't "
                "guess at part numbers, compatibility, procedures or safety requirements."
            )
        else:
            keys = ", ".join(_fact_label(k) for k in conflicts)
            refs = " and ".join(f"[{r}]" for r in sorted(conflict_refs))
            limit = (
                f"The admitted sources I found disagree about the {keys} ({refs}), so I can't "
                "give you a reliable answer on that."
            )
        # Statements checked against the catalogue and central fitment remain true without
        # passages (not when sources conflict: the conflict may be about the part itself).
        checked = "\n".join(f"- {s}" for s in product_statements) if status == "insufficient_evidence" else ""
        text = "\n\n".join(p for p in (checked, limit, _clarifying_question(profile, conflicts)) if p)

    cited_refs = sorted({int(n) for n in CITATION.findall(text) if int(n) in retrieved})
    citations = [_citation(r, retrieved[r]) for r in cited_refs]

    ordered = sorted(product_refs, key=lambda r: (not r.positive, not r.in_stock))[:max_products]
    products = [r.to_response() for r in ordered]
    actions = list(runtime.proposals) if status == "grounded" else []

    if status == "grounded":
        note = f"{len(claims)} statement(s) checked against {len(cited_refs)} admitted source passage(s)."
        if any(retrieved[r].applicability == "unconfirmed" for r in cited_refs):
            note += " Some passages could not be confirmed against your vessel's details."
    elif status == "conflicting":
        note = "Admitted sources conflict on: " + ", ".join(_fact_label(k) for k in conflicts) + "."
    else:
        note = "No admitted source passage supported an answer."
    if removed:
        note += f" {removed} statement(s) without support in the cited sources were removed."
    if any(retrieved[r].is_synthetic for r in cited_refs):
        note += " Cited sources include synthetic test fixtures — not real maintenance, safety or regulatory guidance."
    return GuardResult(text, status, note, cited_refs, citations, products, actions, conflicts, claims, removed)
