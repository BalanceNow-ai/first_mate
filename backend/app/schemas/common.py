"""Shared API contract conventions.

* Money: integer minor units in fields ending ``_cents`` plus ``currency`` ("NZD").
* Identifiers: UUID strings. Timestamps: ISO-8601 with timezone (UTC).
* Errors: ``{"detail": str, "code": str, ...}`` (validation adds ``errors``).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1
MAX_LIST_ITEMS = 500


class APIModel(BaseModel):
    """Base response model reading from ORM attributes."""

    model_config = ConfigDict(from_attributes=True)


def _check_bounds(value: Any, path: str) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int) and not INT32_MIN <= value <= INT32_MAX:
        raise ValueError(f"{path} is out of range")
    if isinstance(value, list | tuple | set):
        if len(value) > MAX_LIST_ITEMS:
            raise ValueError(f"{path} has too many items (max {MAX_LIST_ITEMS})")
        for i, item in enumerate(value):
            _check_bounds(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        if len(value) > MAX_LIST_ITEMS:
            raise ValueError(f"{path} has too many keys (max {MAX_LIST_ITEMS})")
        for k, item in value.items():
            _check_bounds(item, f"{path}.{k}")


class StrictInput(BaseModel):
    """Base request model: rejects unknown fields (no smuggled ids/roles) and values
    the database cannot hold (integers beyond int32, oversized lists)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def _bounded(self):
        for name, value in self.__dict__.items():
            _check_bounds(value, name)
        return self
