"""Knowledge admin router (admin only) and the ingest-knowledge CLI."""

from __future__ import annotations

import argparse

from sqlalchemy import func, select

from app.cli import knowledge as knowledge_cli
from app.config import get_settings
from app.database import async_session
from app.models.ai import KnowledgeSource, RAGDocument
from app.models.ops import AuditLog

SOURCES = "/api/v1/knowledge/sources"
DOC = {
    "title": "Licensed plug guide",
    "publisher": "Example Publisher",
    "url": "https://example.test/guide",
    "licence": "Commercial licence #123 (test)",
    "licence_verified": False,
    "domain": "engine",
    "applies_to": {"engine_make": "Yamaha", "engine_model": "F150"},
    "facts": [{"key": "spark_plug", "value": "SYN-PLUG-150"}],
    "content": "# Spark plugs\n\nThe plug code is SYN-PLUG-150. Replace each season.",
}


async def test_endpoints_are_admin_only(client, customer):
    assert (await client.get(SOURCES)).status_code == 401
    r = await client.get(SOURCES, headers=customer.headers)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert (await client.post(SOURCES, json=DOC, headers=customer.headers)).status_code == 403
    fake = "00000000-0000-0000-0000-000000000001"
    for path in (
        f"{SOURCES}/{fake}/admit",
        f"{SOURCES}/{fake}/revoke",
        f"{SOURCES}/{fake}/reembed",
    ):
        assert (await client.post(path, headers=customer.headers)).status_code == 403
    assert (await client.delete(f"{SOURCES}/{fake}", headers=customer.headers)).status_code == 403


async def test_ingest_admit_revoke_reembed_delete(client, admin):
    r = await client.post(SOURCES, json=DOC, headers=admin.headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "created" and body["superseded_source_ids"] == []
    src = body["source"]
    assert src["admission_status"] == "pending" and src["licence_verified"] is False
    assert src["is_synthetic"] is False and src["chunk_count"] == 1
    assert src["embedding_models"] == ["local_hash-v1"] and len(src["checksum"]) == 64
    sid = src["id"]

    again = await client.post(SOURCES, json=DOC, headers=admin.headers)
    assert again.status_code == 200 and again.json()["status"] == "unchanged"
    assert again.json()["source"]["id"] == sid

    r = await client.post(f"{SOURCES}/{sid}/admit", headers=admin.headers)
    assert r.status_code == 409 and r.json()["code"] == "licence_not_verified"
    r = await client.post(
        f"{SOURCES}/{sid}/admit", json={"licence_verified": True}, headers=admin.headers
    )
    assert r.status_code == 200
    assert r.json()["admission_status"] == "admitted" and r.json()["admitted_by"] == str(admin.id)

    listed = (
        await client.get(SOURCES, params={"status": "admitted"}, headers=admin.headers)
    ).json()
    assert [s["id"] for s in listed] == [sid]
    assert (
        await client.get(SOURCES, params={"domain": "safety"}, headers=admin.headers)
    ).json() == []

    r = await client.post(f"{SOURCES}/{sid}/reembed", headers=admin.headers)
    assert r.status_code == 200 and r.json()["chunks_embedded"] == 1

    changed = {**DOC, "content": DOC["content"] + " Gap check every 50 hours."}
    r = await client.post(SOURCES, json=changed, headers=admin.headers)
    assert r.status_code == 201 and r.json()["status"] == "new_version"
    assert r.json()["superseded_source_ids"] == [sid] and r.json()["source"]["version"] == "2"
    old = (await client.get(f"{SOURCES}/{sid}", headers=admin.headers)).json()
    assert old["admission_status"] == "revoked"

    r = await client.post(f"{SOURCES}/{sid}/revoke", headers=admin.headers)
    assert r.status_code == 200 and r.json()["admission_status"] == "revoked"
    assert (await client.delete(f"{SOURCES}/{sid}", headers=admin.headers)).status_code == 204
    assert (await client.get(f"{SOURCES}/{sid}", headers=admin.headers)).status_code == 404
    async with async_session() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(RAGDocument).where(RAGDocument.source_id == sid)
            )
            == 0
        )
        actions = set((await db.execute(select(AuditLog.action))).scalars())
    assert {
        "knowledge_ingest",
        "knowledge_admit",
        "knowledge_revoke",
        "knowledge_reembed",
        "knowledge_delete",
    } <= actions


async def test_ingest_validation_and_bounds(client, admin, monkeypatch):
    r = await client.post(SOURCES, json={**DOC, "domain": "astrology"}, headers=admin.headers)
    assert r.status_code == 422 and r.json()["code"] == "invalid_domain"
    r = await client.post(
        SOURCES, json={**DOC, "admission_status": "admitted"}, headers=admin.headers
    )
    assert r.status_code == 422  # unknown fields rejected
    r = await client.post(
        SOURCES, json={**DOC, "applies_to": {"colour": "red"}}, headers=admin.headers
    )
    assert r.status_code == 422
    monkeypatch.setattr(get_settings(), "knowledge_max_document_chars", 50)
    r = await client.post(SOURCES, json=DOC, headers=admin.headers)
    assert r.status_code == 413 and r.json()["code"] == "document_too_large"
    assert (
        await client.post(
            f"{SOURCES}/00000000-0000-0000-0000-000000000009/admit", headers=admin.headers
        )
    ).status_code == 404


async def test_ingest_unavailable_when_embeddings_disabled(client, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_provider", "disabled")
    r = await client.post(SOURCES, json=DOC, headers=admin.headers)
    assert r.status_code == 503 and r.json()["code"] == "knowledge_unavailable"


def _args(**kw) -> argparse.Namespace:
    base = dict(
        path=None,
        synthetic=False,
        admit=False,
        title=None,
        publisher=None,
        licence=None,
        domain=None,
        url=None,
        version=None,
        licence_verified=False,
        applies_to_json=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


async def test_cli_synthetic_ingest_and_admit(capsys):
    assert await knowledge_cli.run(_args(synthetic=True)) == 0
    async with async_session() as db:
        statuses = set((await db.execute(select(KnowledgeSource.admission_status))).scalars())
    assert statuses == {"pending"}
    assert await knowledge_cli.run(_args(synthetic=True, admit=True)) == 0
    out = capsys.readouterr().out
    assert "unchanged" in out and "admitted" in out
    async with async_session() as db:
        rows = (await db.execute(select(KnowledgeSource))).scalars().all()
    assert len(rows) == 6 and all(r.admission_status == "admitted" and r.is_synthetic for r in rows)


async def test_cli_synthetic_refused_outside_local(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    assert await knowledge_cli.run(_args(synthetic=True)) == 1


async def test_cli_real_document_stays_pending(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("# Bearings\n\nGrease trailer bearings before each season.", encoding="utf-8")
    code = await knowledge_cli.run(
        _args(
            path=str(path),
            title="Licensed trailer guide",
            publisher="Example",
            licence="Licence #9",
            domain="trailer",
            licence_verified=True,
            applies_to_json="{}",
        )
    )
    assert code == 0
    async with async_session() as db:
        source = (await db.execute(select(KnowledgeSource))).scalar_one()
    assert (
        source.admission_status == "pending" and source.licence_verified and not source.is_synthetic
    )
    assert (
        await knowledge_cli.run(_args(path=str(path), admit=True)) == 2
    )  # no --admit for real content
    assert await knowledge_cli.run(_args(path=str(path))) == 2  # metadata required


def test_cli_is_registered():
    from app.cli.__main__ import main

    try:
        main(["ingest-knowledge", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
