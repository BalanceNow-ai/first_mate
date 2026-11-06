"""Deterministic invoice explanation (SJ-12, SJ-13, SJ-14).

Built from templates over the reviewed fields/lines, the job's problem and preparation
items, and the job's *accepted* scope revisions (each bound to its explicit owner
decision). All arithmetic comes from :mod:`invoice_math`; no model computes or phrases
anything here (``phrasing: deterministic_template``). The content is factual: it never
calls a price fair or unfair, a contractor dishonest, or a line unauthorised — a line
with no approval record is a question to ask. It never triggers a dispute, message,
payment, order, ledger or rewards change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.services.service_jobs import invoice_math as im

EXPLANATION_VERSION = "invoice-explanation-v1"

GLOSSARY: dict[str, str] = {
    "hr": "hour — a time unit printed on the invoice",
    "hrs": "hours — a time unit printed on the invoice",
    "ea": "each — the price for one item",
    "qty": "quantity",
    "pcs": "pieces",
    "pc": "piece",
    "s/s": "stainless steel",
    "ss": "stainless steel",
    "316": "a marine grade of stainless steel (as printed; the grade is not verified)",
    "304": "a general grade of stainless steel (as printed; the grade is not verified)",
    "p/n": "part number",
    "id": "internal diameter (the inside width of a hose or pipe)",
    "od": "outside diameter",
    "r&r": "remove and replace",
    "r/r": "remove and replace",
    "o/b": "outboard",
    "i/b": "inboard",
    "assy": "assembly",
    "misc": "miscellaneous",
    "sundries": "small workshop materials (sealant, cable ties, rags and similar) charged together",
    "consumables": "small materials used up during the job, charged together",
    "call-out": "a charge for attending, separate from the time worked",
    "callout": "a charge for attending, separate from the time worked",
    "gst": "Goods and Services Tax, shown as printed",
    "incl": "including",
    "excl": "excluding",
    "w/o": "work order (or 'without', depending on context)",
    "ltr": "litre",
    "mm": "millimetre",
    "km": "kilometre",
    "imp": "impeller",
    "svc": "service",
    "haul-out": "lifting the boat out of the water",
    "antifoul": "anti-fouling paint for the hull below the waterline",
    "lab": "labour",
}
_GLOSS_RX = {term: re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", re.IGNORECASE) for term in GLOSSARY}

KIND_TEXT = {
    "part": "A part or material supplied",
    "labour": "Labour — time charged for the work",
    "travel": "Travel — a charge for getting to the boat",
    "call_out": "A call-out charge — a fee for attending, separate from time worked",
    "consumable": "Consumables — small materials used up during the job",
    "discount": "A discount — this reduces the amount owed",
    "fee": "A fee or levy",
    "tax": "Tax as printed on the invoice",
    "other": "Another charge",
    "unknown": "A charge that has not been categorised",
}
STOPWORDS = frozenset(
    "the and of for to a an on in with at x ea per hr hrs h mm m new replace replaced replacement supply supplied "
    "fit fitted fitting install installed labour labor work job charge charges cost item items service fee "
    "when under runs run is are was there it its this that from by as or no not".split()
)
LIMITATIONS = [
    "This explanation translates and checks the invoice's own figures. It does not judge whether prices are fair, "
    "whether anyone acted improperly, or give legal or tax advice.",
    "Tax is shown only as printed. No tax rate is assumed and tax compliance is not checked.",
    "Nothing has been sent, disputed, paid or changed. A question is only sent when you choose to send it.",
]


@dataclass
class ExplainContext:
    invoice_id: str
    revision_id: str
    revision_number: int
    revision_status: str
    fields: dict[str, dict]
    lines: list[dict]
    job: dict | None = None
    preparation_items: list[dict] = field(default_factory=list)
    scopes: list[dict] | None = None  # None: no job; [] no accepted scope
    illegible_fields: list[str] = field(default_factory=list)


def tokens(text: str | None) -> set[str]:
    t = (text or "").lower().replace("s/s", "stainless").replace("labor", "labour")
    words = re.findall(r"[a-z0-9]+", t)
    return {w for w in words if len(w) > 1 and w not in STOPWORDS and not w.isdigit()}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def glossary_for(*texts: str | None) -> list[dict]:
    found = []
    joined = " ".join(t for t in texts if t)
    for term, rx in _GLOSS_RX.items():
        if rx.search(joined):
            found.append({"term": term, "meaning": GLOSSARY[term]})
    return found


def _d(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _money(value, currency) -> str:
    return im.fmt(_d(value), currency) if value is not None else "not shown"


def _plain(line: dict, currency: str | None) -> str:
    parts = [KIND_TEXT.get(line["kind"], KIND_TEXT["unknown"])]
    if line.get("description"):
        parts[0] += f": {line['description']}"
    if line.get("part_number"):
        parts.append(f"Part number {line['part_number']} (as printed).")
    q, unit, price = line.get("quantity"), line.get("unit"), line.get("unit_price")
    if q is not None:
        unit_text = unit or (
            "units — the unit is not stated, so it is not assumed to be hours"
            if line["kind"] == "labour"
            else "unit not stated"
        )
        if price is not None:
            parts.append(f"Quantity {im.fmt(_d(q))} ({unit_text}) at {_money(price, currency)} each.")
        else:
            parts.append(f"Quantity {im.fmt(_d(q))} ({unit_text}); no unit price is shown.")
    elif price is not None:
        parts.append(f"Unit price {_money(price, currency)}; no quantity is shown.")
    if line.get("line_total") is not None:
        parts.append(f"Amount shown: {_money(line['line_total'], currency)}.")
    else:
        parts.append("No line amount is shown.")
    if line.get("tax_printed") is not None:
        parts.append(f"Tax printed on this line: {_money(line['tax_printed'], currency)}.")
    return " ".join(p if p.endswith(".") else p + "." for p in parts)


def _related(line: dict, ctx: ExplainContext) -> list[dict]:
    if ctx.job is None:
        return []
    lt = tokens(f"{line.get('description') or ''} {line.get('part_number') or ''}")
    out = []
    for item in ctx.preparation_items:
        if _overlap(lt, tokens(item["name"])) >= 0.5:
            out.append({"type": "preparation_item", "id": item["id"], "name": item["name"], "status": item["status"]})
    problem = tokens(" ".join(str(ctx.job.get(k) or "") for k in ("title", "affected_system", "affected_equipment")))
    shared = sorted(lt & problem)
    if shared:
        out.append(
            {"type": "reported_problem", "id": ctx.job["id"], "name": ctx.job.get("title"), "shared_terms": shared}
        )
    return out


def _scope_lines(scopes: list[dict]) -> list[dict]:
    out = []
    for scope in scopes:
        currency = scope.get("currency")
        for i, est in enumerate(scope.get("estimate_lines") or []):
            if not isinstance(est, dict):
                continue
            qty = est.get("quantity")
            try:
                qty_d = im.to_decimal(qty if not isinstance(qty, float) else str(qty))
            except im.AmountError:
                qty_d = None
            out.append(
                {
                    "scope_revision_id": scope["id"],
                    "scope_revision_number": scope["revision_number"],
                    "is_change": scope["is_change"],
                    "index": i,
                    "description": est.get("description"),
                    "kind": est.get("kind"),
                    "quantity": qty_d,
                    "unit": est.get("unit"),
                    "currency": currency,
                    "unit_price": im.minor_to_major(est.get("unit_price_minor"), currency),
                    "amount": im.minor_to_major(est.get("amount_minor"), currency),
                    "approval": scope["decision"],
                }
            )
    return out


def _approval_text(sl: dict) -> str:
    approval = sl["approval"]
    what = "an accepted change" if sl["is_change"] else "the accepted scope"
    number, day = sl["scope_revision_number"], approval["decided_at"][:10]
    return f"In {what} (scope revision {number}), accepted by the owner on {day}."


# Scope estimate lines and invoice lines use different (plural/singular) kind vocabularies.
SCOPE_KIND_TO_LINE_KIND = {"parts": "part", "consumables": "consumable"}


def _compare(ctx: ExplainContext, checks: dict, questions: list[dict]) -> dict:
    if ctx.job is None:
        return {
            "status": "unavailable",
            "reason": "standalone_invoice",
            "message": "This invoice is not linked to a service job, so there is no accepted scope to compare with.",
            "items": [],
        }
    if not ctx.scopes:
        questions.append(
            {
                "key": "scope:none_on_record",
                "line_id": None,
                "text": "Was there a quote or estimate for this work? If so, could you share it so we can compare "
                "it with the invoice?",
            }
        )
        return {
            "status": "unavailable",
            "reason": "no_accepted_scope",
            "message": "There is no accepted scope or quote on record for this job, so a comparison is unavailable. "
            "This does not mean the work was unauthorised.",
            "items": [],
        }
    currency = checks["currency"]
    scope_lines = _scope_lines(ctx.scopes)
    by_line = {c["line_id"]: c for c in checks["lines"]}
    candidates = []
    for line in ctx.lines:
        if line["kind"] in ("tax", "discount"):
            continue
        lt = tokens(line.get("description"))
        for j, sl in enumerate(scope_lines):
            score = _overlap(lt, tokens(sl["description"]))
            scope_kind = SCOPE_KIND_TO_LINE_KIND.get(sl.get("kind") or "", sl.get("kind"))
            if scope_kind and scope_kind != "other" and line["kind"] not in ("unknown", scope_kind) and score < 0.8:
                continue
            if score >= 0.6:
                candidates.append((score, line["id"], j))
    matched: dict[str, int] = {}
    used: set[int] = set()
    for _score, line_id, j in sorted(candidates, key=lambda c: -c[0]):
        if line_id in matched or j in used:
            continue
        matched[line_id] = j
        used.add(j)
    items = []
    for line in ctx.lines:
        base = {"line_id": line["id"], "line_number": line["line_number"], "description": line.get("description")}
        if line["kind"] in ("tax", "discount"):
            items.append({**base, "status": "not_compared", "differences": [], "approval": None, "approval_text": None})
            continue
        if line["id"] not in matched:
            items.append(
                {
                    **base,
                    "status": "not_in_accepted_scope",
                    "additional_work": True,
                    "differences": [],
                    "approval": None,
                    "approval_text": "No approval record available. This is a question to ask, not a finding "
                    "that the work was unauthorised.",
                }
            )
            questions.append(
                {
                    "key": f"scope:additional:{line['id']}",
                    "line_id": line["id"],
                    "text": f"Line {line['line_number']} ({line.get('description') or 'no description'}) isn't in "
                    "the accepted scope we have on record. Could you let us know when and how this was agreed?",
                }
            )
            continue
        sl = scope_lines[matched[line["id"]]]
        diffs = []
        # A value that cannot be read (or arithmetic that cannot be computed) is never a match.
        unavailable: list[str] = []
        line_check = by_line[line["id"]]
        illegible = set(line.get("illegible") or [])
        if line_check["status"] == "cannot_compute":
            unavailable.append("line_arithmetic_cannot_compute")
        if currency is None or sl["currency"] is None:
            # A missing (or mixed) currency on either side makes the amounts incomparable —
            # never a "difference" and never a match.
            unavailable.append("invoice_currency_unknown" if currency is None else "approved_currency_unknown")
        elif sl["currency"] != currency:
            diffs.append({"field": "currency", "invoice": currency, "approved": sl["currency"]})
        else:
            amount = _d(line_check["amount_used"])
            if amount is None:
                unavailable.append("invoice_amount_unreadable" if illegible else "invoice_amount_unknown")
            if sl["amount"] is None:
                unavailable.append("approved_amount_unknown")
            if amount is not None and sl["amount"] is not None and amount != sl["amount"]:
                diffs.append(
                    {"field": "amount", "invoice": im.fmt(amount, currency), "approved": im.fmt(sl["amount"], currency)}
                )
            price = _d(line.get("unit_price"))
            if price is None and sl["unit_price"] is not None and "unit_price" in illegible:
                unavailable.append("invoice_unit_price_unreadable")
            if price is not None and sl["unit_price"] is not None and price != sl["unit_price"]:
                diffs.append(
                    {
                        "field": "unit_price",
                        "invoice": im.fmt(price, currency),
                        "approved": im.fmt(sl["unit_price"], currency),
                    }
                )
        q = _d(line.get("quantity"))
        if q is None and sl["quantity"] is not None and "quantity" in illegible:
            unavailable.append("invoice_quantity_unreadable")
        if q is not None and sl["quantity"] is not None and q != sl["quantity"]:
            diffs.append({"field": "quantity", "invoice": im.fmt(q), "approved": im.fmt(sl["quantity"])})
        unavailable = list(dict.fromkeys(unavailable))
        approval = {
            "scope_revision_id": sl["scope_revision_id"],
            "scope_revision_number": sl["scope_revision_number"],
            "is_change": sl["is_change"],
            "decision_id": sl["approval"]["id"],
            "decided_at": sl["approval"]["decided_at"],
            "decided_by": sl["approval"]["decided_by"],
            "scope_line_index": sl["index"],
            "scope_line_description": sl["description"],
        }
        items.append(
            {
                **base,
                "status": "comparison_unavailable" if unavailable else ("differs" if diffs else "matches"),
                "unavailable_reasons": unavailable,
                "additional_work": bool(sl["is_change"]),
                "differences": diffs,
                "approval": approval,
                "approval_text": _approval_text(sl),
            }
        )
        if unavailable:
            questions.append(
                {
                    "key": f"scope:unreadable:{line['id']}",
                    "line_id": line["id"],
                    "text": f"Line {line['line_number']} of the invoice can't be compared with scope revision "
                    f"{sl['scope_revision_number']} because a value is missing or unreadable. Could you confirm "
                    "the amount for this line?",
                }
            )
        for d in diffs:
            questions.append(
                {
                    "key": f"scope:differs:{line['id']}:{d['field']}",
                    "line_id": line["id"],
                    "text": f"Scope revision {sl['scope_revision_number']} shows {d['field'].replace('_', ' ')} "
                    f"{d['approved']}; line {line['line_number']} of the invoice shows {d['invoice']}. "
                    "Could you explain the difference?",
                }
            )
    matched_idx = set(matched.values())
    not_invoiced = [
        {
            "scope_revision_id": sl["scope_revision_id"],
            "scope_revision_number": sl["scope_revision_number"],
            "description": sl["description"],
            "amount": im.fmt(sl["amount"], sl["currency"]),
        }
        for j, sl in enumerate(scope_lines)
        if j not in matched_idx
    ]
    return {
        "status": "available",
        "reason": None,
        "message": None,
        "provisional": ctx.revision_status != "owner_reviewed",
        "scope_revisions": [
            {
                "id": s["id"],
                "revision_number": s["revision_number"],
                "is_change": s["is_change"],
                "currency": s.get("currency"),
                "decision_id": s["decision"]["id"],
                "decided_at": s["decision"]["decided_at"],
            }
            for s in ctx.scopes
        ],
        "items": items,
        "scope_lines_not_invoiced": not_invoiced,
    }


_OBLIGATION_RX = re.compile(
    r"warrant|guarantee|follow[\s-]?up|re-?check|inspect again|next service|service due"
    r"|within \d+ (?:days|weeks|months)",
    re.IGNORECASE,
)


def _obligations(ctx: ExplainContext) -> list[dict]:
    out = []
    for name, kind in (("warranty", "warranty"), ("follow_up", "follow_up")):
        f = ctx.fields.get(name) or {}
        if f.get("value"):
            out.append(
                {
                    "kind": kind,
                    "text": f["value"],
                    "source": {"field": name, "line_id": None, "page": f.get("page"), "region": f.get("region")},
                    "note": "As stated on the invoice; First Mate has not verified the terms.",
                }
            )
    for line in ctx.lines:
        desc = line.get("description") or ""
        if _OBLIGATION_RX.search(desc):
            kind = "warranty" if re.search(r"warrant|guarantee", desc, re.IGNORECASE) else "follow_up"
            out.append(
                {
                    "kind": kind,
                    "text": desc,
                    "source": {
                        "field": None,
                        "line_id": line["id"],
                        "line_number": line["line_number"],
                        "page": line.get("page"),
                        "region": line.get("region"),
                    },
                    "note": "As stated on the invoice; First Mate has not verified the terms.",
                }
            )
    return out


def build(ctx: ExplainContext, checks: dict) -> dict:
    """The explanation content (JSON-serialisable)."""
    currency = checks["currency"]
    questions: list[dict] = []
    by_line = {c["line_id"]: c for c in checks["lines"]}
    lines_out = []
    for line in ctx.lines:
        chk = by_line[line["id"]]
        lines_out.append(
            {
                "line_id": line["id"],
                "line_number": line["line_number"],
                "kind": line["kind"],
                "plain_language": _plain(line, currency),
                "glossary": glossary_for(line.get("description"), line.get("unit"), line.get("part_number")),
                "arithmetic": chk,
                "related_to_job": _related(line, ctx),
                "source": {"page": line.get("page"), "region": line.get("region")},
                "certainty": line.get("certainty"),
                "needs_confirmation": line.get("needs_confirmation", False),
            }
        )
        desc = line.get("description") or "no description"
        if chk["status"] == "differs":
            questions.append(
                {
                    "key": f"arith:line:{line['id']}",
                    "line_id": line["id"],
                    "text": f"Line {line['line_number']} ({desc}) shows {_money(line.get('line_total'), currency)}, "
                    f"but {im.fmt(_d(line.get('quantity')))} × {_money(line.get('unit_price'), currency)} works out "
                    f"to {chk['computed']}. Could you confirm how this amount was calculated?",
                }
            )
        if line["kind"] == "labour" and not line.get("unit") and line.get("quantity") is not None:
            questions.append(
                {
                    "key": f"labour_unit:{line['id']}",
                    "line_id": line["id"],
                    "text": f"What unit is the labour quantity on line {line['line_number']} measured in "
                    "(for example, hours)?",
                }
            )
        if line.get("illegible"):
            questions.append(
                {
                    "key": f"illegible:line:{line['id']}",
                    "line_id": line["id"],
                    "text": f"Part of line {line['line_number']} ({desc}) is hard to read. Could you confirm the "
                    f"{', '.join(f.replace('_', ' ') for f in line['illegible'])}?",
                }
            )

    sub, tot = checks["subtotal_check"], checks["total_check"]
    if sub["status"] == "differs":
        questions.append(
            {
                "key": "arith:subtotal",
                "line_id": None,
                "text": f"The line amounts add up to {checks['lines_sum']}, and the printed subtotal is "
                f"{sub['printed']}. Could you explain the difference of {sub['difference']}?",
            }
        )
    if checks["tax"]["source"] == "not_printed":
        questions.append(
            {
                "key": "tax:not_printed",
                "line_id": None,
                "text": "The invoice does not show a tax amount. Could you confirm whether the total includes GST "
                "or any other tax?",
            }
        )
    elif tot["status"] == "differs":
        questions.append(
            {
                "key": "arith:total",
                "line_id": None,
                "text": f"The subtotal plus the printed tax comes to {tot['computed']}, and the printed total is "
                f"{tot['printed']}. Could you explain the difference of {tot['difference']}?",
            }
        )
    if checks["currency_status"] == "missing":
        questions.append({"key": "currency:missing", "line_id": None, "text": "Which currency is this invoice in?"})
    elif checks["currency_status"] == "mixed":
        codes = ", ".join(checks["line_currencies"])
        questions.append(
            {
                "key": "currency:mixed",
                "line_id": None,
                "text": f"The invoice shows amounts in more than one currency ({codes}). Could you confirm the "
                "currency of each amount?",
            }
        )

    duplicates = []
    for ids in im.duplicate_candidates(
        [
            {
                "id": ln["id"],
                "kind": ln["kind"],
                "description": ln.get("description"),
                "part_number": ln.get("part_number"),
                "line_total": ln.get("line_total"),
                "quantity": ln.get("quantity"),
            }
            for ln in ctx.lines
        ]
    ):
        nums = [ln["line_number"] for ln in ctx.lines if ln["id"] in ids]
        first = next(ln for ln in ctx.lines if ln["id"] == ids[0])
        duplicates.append(
            {
                "line_ids": ids,
                "line_numbers": nums,
                "note": "These lines look the same. That may be correct (for example, two separate items); it is a "
                "question to ask, not proof of a duplicate charge.",
            }
        )
        questions.append(
            {
                "key": "dup:" + ",".join(ids),
                "line_id": ids[0],
                "text": f"Lines {' and '.join(str(n) for n in nums)} look the same ({first.get('description')}, "
                f"{_money(first.get('line_total'), currency)}). Could you confirm whether these are separate charges?",
            }
        )

    comparison = _compare(ctx, checks, questions)
    needs = [n for n, f in ctx.fields.items() if f.get("needs_confirmation")] + [
        f"line:{ln['id']}" for ln in ctx.lines if ln.get("needs_confirmation")
    ]
    return {
        "version": EXPLANATION_VERSION,
        "phrasing": "deterministic_template",
        "invoice_id": ctx.invoice_id,
        "revision_id": ctx.revision_id,
        "revision_number": ctx.revision_number,
        "provisional": ctx.revision_status != "owner_reviewed",
        "needs_confirmation": needs,
        "currency": {"code": currency, "status": checks["currency_status"], "exponent": im.exponent(currency)},
        "rounding_policy": checks["rounding_policy_text"],
        "lines": lines_out,
        "arithmetic": checks,
        "comparison": comparison,
        "duplicates": duplicates,
        "obligations": _obligations(ctx),
        "suggested_questions": questions,
        "limitations": LIMITATIONS,
        "attributed_text": [],
    }
