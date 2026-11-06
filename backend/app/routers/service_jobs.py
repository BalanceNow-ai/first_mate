"""Service jobs: create/resume, access details, assignments/grants, evidence requests, visits (workstream A2)."""

from fastapi import APIRouter

router = APIRouter(prefix="/service-jobs", tags=["Service jobs"])
