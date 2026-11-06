"""Case-scoped feedback moderation (workstream D)."""

from fastapi import APIRouter

router = APIRouter(prefix="/moderation", tags=["Moderation"])
