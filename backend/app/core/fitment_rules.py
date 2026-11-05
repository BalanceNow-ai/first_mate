"""Fitment-rule scope contract (FM-02), shared by request validation, verification,
the evaluator and the database CHECK constraints added in migration 0004."""

from __future__ import annotations

RULE_PARENTS = (
    ("vessel_make", ("vessel_model", "year_from", "year_to")),
    ("engine_make", ("engine_model", "engine_year_from", "engine_year_to")),
    ("equipment_category", ("equipment_make", "equipment_model")),
)
RULE_RANGES = (("year_from", "year_to"), ("engine_year_from", "engine_year_to"))
RULE_YEAR_MIN, RULE_YEAR_MAX = 1900, 2100
INCOMPLETE_RULE_REASON = "a fitment rule for this product is incomplete and needs review"


def blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def rule_scope_problems(fields: dict) -> list[str]:
    """Every way a rule's scope is malformed (FM-02). Empty means well-formed.

    A dependent restriction (vessel model/years, engine model/years, equipment
    make/model) is only meaningful with its parent scope; blank strings are absent.
    The same contract is enforced by the create request, verification, the database
    (CHECK constraints, migration 0004) and — fail closed — the evaluator."""
    present = {k: not blank(fields.get(k)) for parent, deps in RULE_PARENTS for k in (parent, *deps)}
    problems = []
    if not any(present[parent] for parent, _ in RULE_PARENTS):
        problems.append("a vessel make, engine make or equipment category is required")
    for parent, deps in RULE_PARENTS:
        if not present[parent]:
            problems += [f"{dep} requires {parent}" for dep in deps if present[dep]]
    for lo, hi in RULE_RANGES:
        for key in (lo, hi):
            value = fields.get(key)
            if value is not None and not RULE_YEAR_MIN <= value <= RULE_YEAR_MAX:
                problems.append(f"{key} must be between {RULE_YEAR_MIN} and {RULE_YEAR_MAX}")
        if fields.get(lo) is not None and fields.get(hi) is not None and fields[lo] > fields[hi]:
            problems.append(f"{lo} must not be after {hi}")
    return problems
