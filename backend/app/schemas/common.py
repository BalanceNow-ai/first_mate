"""Shared API contract conventions.

* Money: integer minor units in fields ending ``_cents`` plus ``currency`` ("NZD").
* Identifiers: UUID strings. Timestamps: ISO-8601 with timezone (UTC).
* Errors: ``{"detail": str, "code": str, ...}`` (validation adds ``errors``).
"""

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    """Base response model reading from ORM attributes."""

    model_config = ConfigDict(from_attributes=True)


class StrictInput(BaseModel):
    """Base request model rejecting unknown fields (no smuggled ids/roles)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
