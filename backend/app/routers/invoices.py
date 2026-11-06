"""Understand my invoice: upload, extraction, corrections, explanation, questions (workstream C)."""

from fastapi import APIRouter

router = APIRouter(prefix="/invoices", tags=["Invoices"])
