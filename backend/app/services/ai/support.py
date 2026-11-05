"""Deterministic claim/evidence support for First Mate answers (decision D21).

A *claim* is any clause of a drafted answer that is not plain framing ("here is what the
sources say:") or a statement about a tool-returned product. A claim is **supported**
only when one admitted passage unit that the same sentence cites:

* contains every number, number+unit pair and identifier (part code, model code) the
  claim states — exactly, after normalisation (``100 hours`` ≠ ``9999 hours``,
  ``100 hours`` ≠ ``100 minutes``, ``10W-30`` ≠ ``10W-40``);
* has the same polarity — a negated passage ("Never run the engine without cooling
  water") cannot support an affirmative claim and vice versa;
* contains the claim's content words: all of them for a quantitative/identifier claim,
  at least ``PARAPHRASE_COVERAGE`` of them otherwise.

Passage units are the sentences of the cited chunk, split into polarity scopes at
contrastive connectives ("but", "however", ";"), plus the chunk's structured facts.

The check is lexical. It does not parse which noun a number belongs to *within one
passage sentence*, so a sentence that lists several intervals can support a claim that
recombines them; and it cannot judge whether a passage is true. It never upgrades a
claim the passage does not lexically contain — unsupported text is removed, never
certified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PARAPHRASE_COVERAGE = 0.75

_WORD = re.compile(r"[a-z0-9°%]+(?:[-'.][a-z0-9]+)*")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
# Polarity scopes: a contrastive connective or a semicolon starts a new scope.
_SCOPE = re.compile(r";|\s(?:but|however|although|though|whereas|while|except)\s", re.IGNORECASE)
# Clauses within a scope (they inherit the scope's polarity).
_CLAUSE = re.compile(r"[,;]|\s(?:and|or|then|so|which|whichever)\s", re.IGNORECASE)

_NEGATIONS = {"not", "no", "never", "nor", "cannot", "neither", "none", "nothing"}
_NEGATION_STEMS = ("avoid",)

STOPWORDS = {
    "a",
    "an",
    "the",
    "to",
    "of",
    "in",
    "on",
    "at",
    "by",
    "for",
    "with",
    "and",
    "or",
    "but",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "you",
    "your",
    "yours",
    "we",
    "our",
    "us",
    "i",
    "my",
    "me",
    "as",
    "if",
    "so",
    "then",
    "than",
    "there",
    "their",
    "they",
    "them",
    "from",
    "into",
    "about",
    "every",
    "each",
    "can",
    "could",
    "may",
    "might",
    "should",
    "must",
    "will",
    "would",
    "shall",
    "do",
    "does",
    "did",
    "done",
    "have",
    "has",
    "had",
    "please",
    "also",
    "just",
    "only",
    "any",
    "all",
    "some",
    "very",
    "up",
    "out",
    "use",
    "used",
    "using",
    "uses",
    "when",
    "whenever",
    "after",
    "before",
    "per",
    "any",
    "via",
    "which",
    "whichever",
    "what",
    "who",
    "how",
    "here",
    "s",
    "re",
    "ll",
    "ve",
    "d",
    "t",
    "also",
    "first",
    "comes",
}

NUMBER_WORDS = {
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "half",
    "double",
    "twice",
    "dozen",
}

_UNIT_ALIASES = {
    "hour": "hour",
    "hr": "hour",
    "hrs": "hour",
    "h": "hour",
    "minut": "minute",
    "min": "minute",
    "mins": "minute",
    "second": "second",
    "sec": "second",
    "secs": "second",
    "day": "day",
    "week": "week",
    "month": "month",
    "year": "year",
    "yr": "year",
    "season": "season",
    "litr": "litre",
    "liter": "litre",
    "l": "litre",
    "ml": "millilitre",
    "millilitr": "millilitre",
    "metr": "metre",
    "meter": "metre",
    "m": "metre",
    "mm": "millimetre",
    "cm": "centimetre",
    "km": "kilometre",
    "ft": "foot",
    "foot": "foot",
    "feet": "foot",
    "inch": "inch",
    "kg": "kilogram",
    "g": "gram",
    "gram": "gram",
    "lb": "pound",
    "pound": "pound",
    "psi": "psi",
    "bar": "bar",
    "kpa": "kpa",
    "nm": "newton_metre",
    "rpm": "rpm",
    "v": "volt",
    "volt": "volt",
    "a": "amp",
    "amp": "amp",
    "ah": "amp_hour",
    "w": "watt",
    "watt": "watt",
    "kw": "kilowatt",
    "hp": "horsepower",
    "knot": "knot",
    "kt": "knot",
    "mile": "mile",
    "nmi": "nautical_mile",
    "%": "percent",
    "percent": "percent",
    "degre": "degree",
    "°c": "degree_c",
    "°f": "degree_f",
    "c": "degree_c",
}


def _stem(word: str) -> str:
    if any(ch.isdigit() for ch in word) or len(word) <= 3:
        return word
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def _is_numeric(token: str) -> bool:
    return any(ch.isdigit() for ch in token) or token in NUMBER_WORDS


def _is_negation(token: str) -> bool:
    return token in _NEGATIONS or token.endswith("n't") or token.startswith(_NEGATION_STEMS)


def words(text: str) -> list[str]:
    return _WORD.findall(_THOUSANDS.sub("", text.lower().replace("’", "'")))


def content_tokens(text: str) -> set[str]:
    out = set()
    for w in words(text):
        w = w.strip("'.")
        if not w or w in STOPWORDS or _is_negation(w):
            continue
        out.add(_stem(w))
    return out


def is_negative(text: str) -> bool:
    return any(_is_negation(w) for w in words(text))


def _numerics(tokens: set[str]) -> set[str]:
    return {t for t in tokens if _is_numeric(t)}


def _unit(word: str) -> str | None:
    return _UNIT_ALIASES.get(word) or _UNIT_ALIASES.get(_stem(word))


def _pairs(text: str) -> set[tuple[str, str]]:
    """(number, unit) pairs: a unit within the next two words of a bare number."""
    ws = [w.strip("'.") for w in words(text)]
    pairs = set()
    for i, w in enumerate(ws):
        if not (w.replace(".", "", 1).isdigit() or w in NUMBER_WORDS):
            continue
        for nxt in ws[i + 1 : i + 3]:
            unit = _unit(nxt)
            if unit:
                pairs.add((w, unit))
                break
    return pairs


@dataclass(frozen=True)
class Unit:
    """One piece of passage evidence: a polarity scope of a sentence, or a structured fact."""

    ref: int
    text: str
    tokens: frozenset[str]
    pairs: frozenset[tuple[str, str]]
    negative: bool


@dataclass
class Clause:
    text: str
    tokens: set[str]
    pairs: set[tuple[str, str]]
    negative: bool

    @property
    def numerics(self) -> set[str]:
        return _numerics(self.tokens)


@dataclass
class Support:
    supported: bool
    evidence: list[Unit] = field(default_factory=list)


def scopes(sentence: str) -> list[str]:
    return [s.strip() for s in _SCOPE.split(sentence) if s and s.strip()]


def clauses(sentence: str) -> list[Clause]:
    """Split a claim sentence into clauses that inherit their scope's polarity."""
    out = []
    for scope in scopes(sentence):
        negative = is_negative(scope)
        for part in _CLAUSE.split(scope):
            if part and part.strip():
                out.append(Clause(part.strip(), content_tokens(part), _pairs(part), negative))
    return out


def passage_units(ref: int, content: str, facts: list[dict]) -> list[Unit]:
    units: list[Unit] = []
    for raw in _SENTENCE.split(" ".join(content.split())):
        sentence = raw.strip().lstrip("#>-*• ").strip()
        if not sentence:
            continue
        parts = scopes(sentence)
        polarities = {is_negative(p) for p in parts}
        if len(parts) > 1 and len(polarities) == 1:
            units.append(_unit_for(ref, sentence, polarities.pop()))
        for part in parts:
            units.append(_unit_for(ref, part, is_negative(part)))
    for fact in facts or []:
        key = str(fact.get("key", "")).replace("_", " ").strip()
        value = str(fact.get("value", "")).strip()
        if not value:
            continue
        label = str(fact.get("label") or key)
        text = f"{label}: {value}"
        tokens = content_tokens(f"{label} {key} {value}")
        pairs = _pairs(f"{value} {key}") | _pairs(text)
        units.append(Unit(ref, text, frozenset(tokens), frozenset(pairs), is_negative(value)))
    return units


def _unit_for(ref: int, text: str, negative: bool) -> Unit:
    return Unit(ref, text, frozenset(content_tokens(text)), frozenset(_pairs(text)), negative)


def clause_supported_by(clause: Clause, unit: Unit) -> bool:
    if not clause.tokens:
        return True
    if clause.negative != unit.negative:
        return False
    if not clause.numerics <= unit.tokens:
        return False
    if not clause.pairs <= unit.pairs:
        return False
    covered = len(clause.tokens & unit.tokens) / len(clause.tokens)
    return covered >= (1.0 if clause.numerics else PARAPHRASE_COVERAGE)


def support(clause: Clause, units: list[Unit]) -> Support:
    """The best supporting unit for a claim clause (fewest extra words), if any."""
    candidates = [u for u in units if clause_supported_by(clause, u)]
    if not candidates:
        return Support(False)
    return Support(True, [min(candidates, key=lambda u: len(u.tokens))])
