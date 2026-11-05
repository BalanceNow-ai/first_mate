"""Deterministic claim/evidence support for First Mate answers (decision D21).

A *claim* is any clause of a drafted answer that is not plain framing ("here is what the
sources say:") or a statement about a tool-returned product. A claim sentence is
**supported** only when ONE sentence (or structured fact) of a passage that the claim
sentence itself cites:

* contains every content word of all the claim's clauses (after light stemming) —
  there is no paraphrase allowance, so "check" cannot become "disable", "without"
  cannot become "with" and "before" cannot become "after";
* contains every number, number+unit pair and identifier exactly, after normalisation
  (``100 hours`` = ``100-hour`` = ``100 h``; ``10W-30`` = ``10W30``; but ``100 hours`` ≠
  ``9999 hours`` ≠ ``100 minutes``);
* agrees in polarity clause by clause: each claim clause must have the same negation as
  the clause of that passage sentence it overlaps most (numbers and identifiers weigh
  double); ties must all agree.

Because the whole claim must sit in one passage sentence, statements from different
passage sentences cannot be recombined ("every 300 hours, change the oil" against
"oil every 100 hours. Impeller every 300 hours." is unsupported).

Limits: the check is lexical. Within ONE passage sentence that lists several values it
cannot tell which noun each value belongs to; it cannot judge whether a passage is true
or whether it applies more finely than its declared scope. It never upgrades text the
passage does not lexically contain — unsupported text is removed, never certified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_WORD = re.compile(r"[a-z0-9°%]+(?:[-'.][a-z0-9]+)*")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
# Clauses (each with its own polarity).
_CLAUSE = re.compile(
    r"[,;:]|\s(?:and|or|nor|then|so|which|whichever|but|however|although|though|whereas|while|except)\s",
    re.IGNORECASE,
)
_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "approx.", "vs.", "no.", "min.", "max.", "incl.", "esp.", "fig.", "cf.")

_NEGATIONS = {"not", "no", "never", "nor", "cannot", "neither", "none", "nothing"}
_NEGATION_STEMS = ("avoid",)

# Only words with no bearing on what is claimed. Prepositions of relation, time and
# quantity (with, before, after, every, only, all, …) are content and must match.
STOPWORDS = {
    "a",
    "an",
    "the",
    "to",
    "of",
    "and",
    "or",
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
    "they",
    "them",
    "their",
    "there",
    "as",
    "so",
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
    "very",
    "use",
    "used",
    "using",
    "uses",
    "which",
    "whichever",
    "here",
    "s",
    "re",
    "ll",
    "ve",
    "d",
    "t",
    # Prepositions with no reversible meaning (with/without, before/after, on/off, above/
    # below, over/under, more/less, every/only/all/any stay content and must match).
    "in",
    "at",
    "by",
    "for",
    "from",
    "into",
    "about",
    "per",
    "via",
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
_NUMBER_UNIT = re.compile(r"\b(\d+(?:\.\d+)?)-?([a-z%°]{1,8})\b(?![-\d])")


def split_sentences(text: str) -> list[str]:
    """Sentence split that does not break after common abbreviations ("e.g. on a trailer")."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    out: list[str] = []
    for part in parts:
        if out and out[-1].lower().endswith(_ABBREVIATIONS):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def _stem(word: str) -> str:
    if any(ch.isdigit() for ch in word) or len(word) <= 3:
        return word
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def _unit(word: str) -> str | None:
    return _UNIT_ALIASES.get(word) or _UNIT_ALIASES.get(_stem(word))


def _normalise(text: str) -> str:
    text = _THOUSANDS.sub("", text.lower().replace("’", "'"))
    # "100-hour", "100h", "12v" → "100 hour", "100 h", "12 v" when the suffix is a unit.
    return _NUMBER_UNIT.sub(lambda m: f"{m.group(1)} {m.group(2)}" if _unit(m.group(2)) else m.group(0), text)


def _is_numeric(token: str) -> bool:
    return any(ch.isdigit() for ch in token) or token in NUMBER_WORDS


def _is_negation(token: str) -> bool:
    return token in _NEGATIONS or token.endswith("n't") or token.startswith(_NEGATION_STEMS)


def words(text: str) -> list[str]:
    return [w.strip("'.") for w in _WORD.findall(_normalise(text))]


def _token(word: str) -> str:
    if any(ch.isdigit() for ch in word):
        return word.replace("-", "")  # identifiers: 10W-30 == 10W30
    unit = _unit(word)
    return unit if unit else _stem(word)


def content_tokens(text: str) -> set[str]:
    out = set()
    for w in words(text):
        if not w or w in STOPWORDS or _is_negation(w):
            continue
        out.add(_token(w))
    return out


def is_negative(text: str) -> bool:
    """ "without" is a content word, not negation: it must match the passage literally."""
    return any(_is_negation(w) for w in words(text))


def _pairs(text: str) -> set[tuple[str, str]]:
    """(number, unit) pairs: a unit within the next two words of a bare number."""
    ws = words(text)
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


@dataclass
class Clause:
    text: str
    tokens: set[str]
    pairs: set[tuple[str, str]]
    negative: bool

    @property
    def numerics(self) -> set[str]:
        return {t for t in self.tokens if _is_numeric(t)}


@dataclass(frozen=True)
class Unit:
    """One piece of passage evidence: a sentence (with its clauses) or a structured fact."""

    ref: int
    text: str
    tokens: frozenset[str]
    pairs: frozenset[tuple[str, str]]
    clauses: tuple[tuple[frozenset[str], bool], ...]


@dataclass
class Support:
    supported: bool
    evidence: list[Unit] = field(default_factory=list)


def clauses(sentence: str) -> list[Clause]:
    """Split a sentence into clauses, each with its own polarity."""
    return [
        Clause(part.strip(), content_tokens(part), _pairs(part), is_negative(part))
        for part in _CLAUSE.split(sentence)
        if part and part.strip()
    ]


def passage_units(ref: int, content: str, facts: list[dict]) -> list[Unit]:
    units: list[Unit] = []
    for raw in split_sentences(" ".join(content.split())):
        sentence = raw.strip().lstrip("#>-*• ").strip()
        if not sentence:
            continue
        parts = clauses(sentence)
        units.append(
            Unit(
                ref,
                sentence,
                frozenset(content_tokens(sentence)),
                frozenset(_pairs(sentence)),
                tuple((frozenset(c.tokens), c.negative) for c in parts),
            )
        )
    for fact in facts or []:
        key = str(fact.get("key", "")).replace("_", " ").strip()
        value = str(fact.get("value", "")).strip()
        if not value:
            continue
        label = str(fact.get("label") or key)
        text = f"{label}: {value}"
        tokens = frozenset(content_tokens(f"{label} {key} {value}"))
        pairs = set(_pairs(text))
        if value.replace(".", "", 1).isdigit():
            pairs |= {(value, u) for w in words(f"{label} {key}") if (u := _unit(w))}
        negative = is_negative(value)
        units.append(Unit(ref, text, tokens, frozenset(pairs), ((tokens, negative),)))
    return units


def _weight(tokens) -> int:
    return sum(2 if _is_numeric(t) else 1 for t in tokens)


def supported_by(claim: list[Clause], unit: Unit) -> bool:
    """Whether one passage unit supports every clause of a claim sentence."""
    tokens = set().union(*(c.tokens for c in claim))
    pairs = set().union(*(c.pairs for c in claim))
    if not tokens or not tokens <= unit.tokens or not pairs <= unit.pairs:
        return False
    for clause in claim:
        if not clause.tokens:
            continue
        scored = [(_weight(clause.tokens & toks), negative) for toks, negative in unit.clauses]
        best = max(score for score, _ in scored)
        if best == 0 or any(neg != clause.negative for score, neg in scored if score == best):
            return False
    return True


def support(claim: list[Clause], units: list[Unit]) -> Support:
    """The tightest single passage unit supporting the whole claim sentence, if any."""
    candidates = [u for u in units if supported_by(claim, u)]
    if not candidates:
        return Support(False)
    return Support(True, [min(candidates, key=lambda u: len(u.tokens))])
