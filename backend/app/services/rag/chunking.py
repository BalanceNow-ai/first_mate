"""Front-matter parsing and heading-aware chunking of text/markdown documents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LEADING_COMMENT = re.compile(r"^\s*<!--.*?-->\s*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class FrontMatterError(ValueError):
    pass


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Split ``text`` into (metadata, body).

    Front matter is a block delimited by ``---`` lines at the top of the file (leading
    HTML comment lines are allowed before it). Each line is ``key: value``; values
    that look like JSON (objects, lists, strings, numbers, booleans, null) are parsed
    as JSON, everything else is a plain string. No YAML dependency is needed.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines) and (not lines[i].strip() or _LEADING_COMMENT.match(lines[i])):
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return {}, text
    meta: dict = {}
    j = i + 1
    while j < len(lines) and lines[j].strip() != "---":
        line = lines[j]
        j += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise FrontMatterError(f"Invalid front matter line: {line[:60]!r}")
        key, raw = line.split(":", 1)
        key, raw = key.strip(), raw.strip()
        if raw[:1] in '[{"' or raw in ("true", "false", "null") or re.fullmatch(r"-?\d+(\.\d+)?", raw):
            try:
                meta[key] = json.loads(raw)
                continue
            except json.JSONDecodeError as exc:
                raise FrontMatterError(f"Invalid JSON value for {key!r}") from exc
        meta[key] = raw
    if j >= len(lines):
        raise FrontMatterError("Unterminated front matter block")
    return meta, "\n".join(lines[j + 1 :]).strip("\n")


@dataclass
class Chunk:
    index: int
    heading: str | None
    content: str
    facts: list[dict] = field(default_factory=list)


@dataclass
class _Section:
    heading: str | None
    paragraphs: list[str]


def _sections(body: str) -> list[_Section]:
    sections: list[_Section] = []
    path: list[tuple[int, str]] = []
    current = _Section(None, [])
    buffer: list[str] = []

    def flush_paragraph() -> None:
        if buffer:
            para = "\n".join(buffer).strip()
            if para:
                current.paragraphs.append(para)
            buffer.clear()

    for line in body.split("\n"):
        m = _HEADING.match(line)
        if m:
            flush_paragraph()
            if current.paragraphs:
                sections.append(current)
            level, title = len(m.group(1)), m.group(2).strip()
            path = [(lvl, t) for lvl, t in path if lvl < level] + [(level, title)]
            current = _Section(" > ".join(t for _, t in path), [])
        elif not line.strip():
            flush_paragraph()
        else:
            buffer.append(line.rstrip())
    flush_paragraph()
    if current.paragraphs:
        sections.append(current)
    return sections


def _split_long(text: str, size: int) -> list[str]:
    """Split one over-long paragraph by sentences, hard-splitting giant sentences."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT.split(text):
        while len(sentence) > size:
            pieces.append(sentence[:size])
            sentence = sentence[size:]
        if current and len(current) + 1 + len(sentence) > size:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    # Start the overlap at a sentence/word boundary.
    m = re.search(r"(?<=[.!?])\s+", tail)
    if m:
        return tail[m.end() :]
    space = tail.find(" ")
    return tail[space + 1 :] if space >= 0 else tail


def chunk_document(body: str, size: int = 800, overlap: int = 120) -> list[Chunk]:
    """Heading-aware chunking: chunks never span two sections; long sections are split
    on paragraph/sentence boundaries into ~``size`` character chunks with ``overlap``."""
    chunks: list[Chunk] = []
    for section in _sections(body):
        units: list[str] = []
        for para in section.paragraphs:
            units.extend(_split_long(para, size) if len(para) > size else [para])
        current = ""
        for unit in units:
            if current and len(current) + 2 + len(unit) > size:
                chunks.append(Chunk(len(chunks), section.heading, current))
                prefix = _tail(current, overlap)
                current = f"{prefix} {unit}".strip() if prefix else unit
            else:
                current = f"{current}\n\n{unit}" if current else unit
        if current:
            chunks.append(Chunk(len(chunks), section.heading, current))
    return chunks


def attach_facts(chunks: list[Chunk], facts: list[dict]) -> None:
    """Attach each declared fact to the chunks whose text states its value.

    A fact with a ``heading`` is attached to chunks under that heading. A fact whose
    value appears nowhere is attached to every chunk (it describes the whole source).
    """
    for fact in facts:
        value = str(fact.get("value", "")).lower()
        heading = fact.get("heading")
        targets = [
            c
            for c in chunks
            if (heading and c.heading and heading.lower() in c.heading.lower())
            or (not heading and value and value in c.content.lower())
        ]
        for c in targets or chunks:
            c.facts.append({k: fact[k] for k in ("key", "value", "label") if k in fact})
