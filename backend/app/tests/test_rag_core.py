"""Embeddings, chunking, front matter, ingestion versioning and retrieval filters."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.config import get_settings
from app.core.errors import AppError
from app.database import async_session
from app.models.ai import KnowledgeSource, RAGDocument
from app.models.vessel import Vessel
from app.services import fitment
from app.services.rag import embeddings
from app.services.rag.chunking import attach_facts, chunk_document, parse_front_matter
from app.services.rag.ingestion import SourceMetadata, admit, ingest, revoke
from app.services.rag.retrieval import applicability, retrieve
from app.services.rag.seed import (
    SYNTHETIC_LICENCE,
    SYNTHETIC_PUBLISHER,
    fixture_paths,
    ingest_synthetic_corpus,
    load_fixture,
)
from app.tests.conftest import create_vessel

F150 = "Synthetic service notes — Yamaha F150 outboard"


# ------------------------------------------------------------------ embeddings
async def test_local_hash_is_deterministic_normalised_and_discriminative():
    e = embeddings.LocalHashEmbedder()
    a1, a2, b = await e.embed(
        [
            "Replace the spark plugs every season",
            "Replace the spark plugs every season",
            "Check the anchor chain for rust",
        ]
    )
    assert a1 == a2
    assert len(a1) == 1536
    assert math.isclose(sum(v * v for v in a1), 1.0, rel_tol=1e-9)
    cos = sum(x * y for x, y in zip(a1, b, strict=True))
    near = sum(
        x * y for x, y in zip(a1, e.embed_one("When should I replace spark plugs?"), strict=True)
    )
    assert near > 0.3 and abs(cos) < 0.1
    assert e.model_id == "local_hash-v1"
    assert e.embed_one("the and of") == [0.0] * 1536  # stopwords only


async def test_openai_embedder_batches_with_fake_client(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_batch_size", 2)
    calls = []

    class FakeEmbeddings:
        async def create(self, **kwargs):
            calls.append(kwargs)
            data = [
                SimpleNamespace(index=i, embedding=[float(i + 1)] * 1536)
                for i in range(len(kwargs["input"]))
            ]
            return SimpleNamespace(data=list(reversed(data)))

    e = embeddings.OpenAIEmbedder(settings, client=SimpleNamespace(embeddings=FakeEmbeddings()))
    vectors = await e.embed(["a", "b", "c"])
    assert [len(c["input"]) for c in calls] == [2, 1]
    assert all(
        c["model"] == settings.openai_embedding_model and c["dimensions"] == 1536 for c in calls
    )
    assert all(c["timeout"] == settings.ai_request_timeout_seconds for c in calls)
    assert [v[0] for v in vectors] == [1.0, 2.0, 1.0]  # re-ordered by index
    assert e.model_id == "text-embedding-3-small"


async def test_openai_embedder_error_is_generic(monkeypatch):
    class Boom:
        async def create(self, **kwargs):
            raise RuntimeError("sk-secret leaked")

    e = embeddings.OpenAIEmbedder(get_settings(), client=SimpleNamespace(embeddings=Boom()))
    with pytest.raises(AppError) as exc:
        await e.embed(["x"])
    assert exc.value.code == "knowledge_unavailable" and "sk-secret" not in exc.value.message


def test_embedder_selection(monkeypatch):
    settings = get_settings()
    assert isinstance(embeddings.get_embedder(), embeddings.LocalHashEmbedder)
    monkeypatch.setattr(settings, "embedding_provider", "disabled")
    with pytest.raises(AppError) as exc:
        embeddings.get_embedder()
    assert exc.value.status_code == 503
    monkeypatch.setattr(settings, "embedding_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert not embeddings.embeddings_available()
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    assert isinstance(embeddings.get_embedder(), embeddings.OpenAIEmbedder)
    assert embeddings.active_model_id() == "text-embedding-3-small"
    monkeypatch.setattr(settings, "embedding_provider", "local_hash")
    monkeypatch.setattr(settings, "app_env", "production")
    assert not embeddings.embeddings_available()  # local substitute refused outside dev/test


# -------------------------------------------------------- front matter / chunking
def test_front_matter_parsing():
    meta, body = parse_front_matter(
        "<!-- note -->\n---\ntitle: A: B\nis_synthetic: true\nversion: 2\n"
        'applies_to: {"engine_make": "Yamaha"}\nfacts: [{"key": "k", "value": "V-1"}]\n---\n# H\n\nText\n'
    )
    assert meta == {
        "title": "A: B",
        "is_synthetic": True,
        "version": 2,
        "applies_to": {"engine_make": "Yamaha"},
        "facts": [{"key": "k", "value": "V-1"}],
    }
    assert body == "# H\n\nText"
    assert parse_front_matter("no front matter") == ({}, "no front matter")


def test_heading_aware_chunking_with_overlap():
    long_para = " ".join(
        f"Sentence number {i} explains a maintenance step in detail." for i in range(40)
    )
    body = f"Intro line.\n\n# Engine\n\n## Spark plugs\n\nShort plug text SYN-X-1.\n\n## Impeller\n\n{long_para}\n"
    chunks = chunk_document(body, size=300, overlap=80)
    assert chunks[0].heading is None and chunks[0].content == "Intro line."
    assert chunks[1].heading == "Engine > Spark plugs"
    impeller = [c for c in chunks if c.heading == "Engine > Impeller"]
    assert len(impeller) > 3 and all(len(c.content) <= 300 + 80 for c in impeller)
    # consecutive chunks overlap
    assert impeller[1].content.split(" ")[0:3] != impeller[0].content.split(" ")[0:3]
    tail_words = impeller[0].content.split()[-3:]
    assert " ".join(tail_words) in impeller[1].content
    assert [c.index for c in chunks] == list(range(len(chunks)))
    attach_facts(
        chunks, [{"key": "plug", "value": "SYN-X-1"}, {"key": "whole", "value": "nowhere"}]
    )
    assert {"key": "plug", "value": "SYN-X-1"} in chunks[1].facts
    assert all({"key": "plug", "value": "SYN-X-1"} not in c.facts for c in impeller)
    assert all({"key": "whole", "value": "nowhere"} in c.facts for c in chunks)


def test_seed_fixtures_are_all_synthetic():
    paths = fixture_paths()
    assert len(paths) >= 6
    for path in paths:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        assert (
            "SYNTHETIC" in first_line
            and "not real maintenance, safety or regulatory guidance" in first_line
        )
        meta, body = load_fixture(path)
        assert (
            meta.is_synthetic
            and meta.publisher == SYNTHETIC_PUBLISHER
            and meta.licence == SYNTHETIC_LICENCE
        )
        body_first = body.strip().splitlines()[0]
        assert "synthetic" in body_first.lower() and "not real maintenance" in body_first


# ---------------------------------------------------------------- ingestion
def _meta(**kw) -> SourceMetadata:
    base = dict(
        title="Doc", publisher="Pub", licence="Licensed", licence_verified=True, domain="engine"
    )
    base.update(kw)
    return SourceMetadata(**base)


async def test_ingest_is_idempotent_and_versions_revoke_old():
    async with async_session() as db:
        first = await ingest(db, _meta(), "# Plugs\n\nChange plugs every season.")
        assert first.status == "created" and first.source.admission_status == "pending"
        assert first.source.version == "1"
        await admit(db, first.source.id, None)
        again = await ingest(db, _meta(), "# Plugs\n\nChange plugs every season.")
        assert again.status == "unchanged" and again.source.id == first.source.id
        changed = await ingest(db, _meta(), "# Plugs\n\nChange plugs every 50 hours.")
        assert changed.status == "new_version" and changed.superseded_ids == [first.source.id]
        assert changed.source.version == "2" and changed.source.admission_status == "pending"
        await db.refresh(first.source)
        assert first.source.admission_status == "revoked"
        chunks = (
            (
                await db.execute(
                    select(RAGDocument).where(RAGDocument.source_id == changed.source.id)
                )
            )
            .scalars()
            .all()
        )
        assert all(c.embedding_model == "local_hash-v1" and c.embedding is not None for c in chunks)
        assert first.source.checksum != changed.source.checksum
        await db.commit()


async def test_ingest_validation():
    async with async_session() as db:
        with pytest.raises(AppError) as exc:
            await ingest(db, _meta(domain="astrology"), "text")
        assert exc.value.code == "invalid_domain"
        with pytest.raises(AppError) as exc:
            await ingest(db, _meta(applies_to={"hull_colour": "red"}), "text")
        assert exc.value.code == "invalid_metadata"
        with pytest.raises(AppError) as exc:
            await ingest(db, _meta(), "x" * (get_settings().knowledge_max_document_chars + 1))
        assert exc.value.status_code == 413
        with pytest.raises(AppError):
            await ingest(db, _meta(), "   ")


async def test_admission_requires_verified_licence(monkeypatch):
    async with async_session() as db:
        real = await ingest(
            db, _meta(title="Real", licence_verified=False), "# A\n\nText about plugs."
        )
        with pytest.raises(AppError) as exc:
            await admit(db, real.source.id, None)
        assert exc.value.code == "licence_not_verified"
        synthetic = await ingest(
            db, _meta(title="Synth", licence_verified=False, is_synthetic=True), "# A\n\nPlugs."
        )
        assert (await admit(db, synthetic.source.id, None)).admission_status == "admitted"
        await revoke(db, synthetic.source.id, None)
        monkeypatch.setattr(get_settings(), "app_env", "production")
        with pytest.raises(AppError):
            await admit(db, synthetic.source.id, None)  # synthetic exemption is local-only
        monkeypatch.setattr(get_settings(), "app_env", "test")
        assert (
            await admit(db, real.source.id, None, licence_verified=True)
        ).admission_status == "admitted"
        await db.commit()


# ---------------------------------------------------------------- retrieval
async def _profile(db, vessel_id):
    return await fitment.load_vessel_profile(db, await db.get(Vessel, vessel_id))


async def test_retrieval_filters_admission_applicability_and_model(customer):
    vessel = await create_vessel(customer.id)
    async with async_session() as db:
        await ingest_synthetic_corpus(db, admit_sources=True)
        pending = await ingest(
            db, _meta(title="Pending plugs"), "# Spark plugs\n\nSpark plugs spark plugs change."
        )
        legacy_vector = embeddings.LocalHashEmbedder().embed_one("spark plugs change")
        db.add(
            RAGDocument(
                source_id=None,
                agent_domain="engine",
                source="legacy",
                content="spark plugs change",
                embedding=legacy_vector,
                embedding_model="local_hash-v1",
            )
        )
        await db.commit()
    q = "When should I change the spark plugs?"
    async with async_session() as db:
        results = await retrieve(db, q, await _profile(db, vessel.id))
        titles = [c.title for c in results]
        assert titles[0] == F150 and results[0].applicability == "matches"
        assert results[0].similarity >= get_settings().rag_min_similarity
        assert {
            "key": "spark_plug",
            "value": "SYN-PLUG-150",
            "label": "Spark plug (synthetic code)",
        } in results[0].facts
        assert not any("DF140" in t or "HX90" in t for t in titles)
        assert "Pending plugs" not in titles and "legacy" not in titles
        assert all(c.source_id != pending.source.id for c in results)
        assert len(results) <= get_settings().rag_top_k
        # Domain filter.
        assert await retrieve(db, q, await _profile(db, vessel.id), domains=["safety"]) == []

    # Engine change flips applicability.
    async with async_session() as db:
        await db.execute(
            update(Vessel)
            .where(Vessel.id == vessel.id)
            .values(engine_make="Suzuki", engine_model="DF140")
        )
        await db.commit()
    async with async_session() as db:
        titles = [c.title for c in await retrieve(db, q, await _profile(db, vessel.id))]
        assert "Synthetic service notes — Suzuki DF140 outboard" in titles and F150 not in titles

    # Chunks embedded with another model are never compared.
    async with async_session() as db:
        await db.execute(update(RAGDocument).values(embedding_model="text-embedding-3-small"))
        await db.commit()
    async with async_session() as db:
        assert await retrieve(db, q, await _profile(db, vessel.id)) == []


async def test_revocation_and_deletion_remove_from_retrieval(customer):
    vessel = await create_vessel(customer.id)
    async with async_session() as db:
        await ingest_synthetic_corpus(db, admit_sources=True)
        await db.commit()
    q = "When should I change the spark plugs?"
    async with async_session() as db:
        f150 = (
            await db.execute(select(KnowledgeSource).where(KnowledgeSource.title == F150))
        ).scalar_one()
        assert F150 in [c.title for c in await retrieve(db, q, await _profile(db, vessel.id))]
        await revoke(db, f150.id, None)
        assert F150 not in [c.title for c in await retrieve(db, q, await _profile(db, vessel.id))]


def test_applicability_rules():
    from app.services.fitment import EquipmentFact, VesselProfile

    def prof(make=None, model=None):
        p = VesselProfile(vessel_id=None, nickname="B", make="Stabicraft", model="2050", year=2020)
        if make:
            p.facts.append(EquipmentFact("engine", make, model, None, 1, "vessel_record"))
        return p

    yam = {"engine_make": "Yamaha", "engine_model": "F150"}
    assert applicability({}, prof("Yamaha", "F150")) == "general"
    assert applicability(yam, prof("yamaha", "F-150")) == "matches"
    assert applicability(yam, prof("Suzuki", "DF140")) is None
    assert applicability(yam, prof("Yamaha", "F200")) is None
    assert applicability(yam, prof("Yamaha", None)) == "unconfirmed"
    assert applicability(yam, prof()) == "unconfirmed"
    assert applicability(yam, None) == "unconfirmed"
    assert applicability({"vessel_make": "Rayglass"}, prof("Yamaha", "F150")) is None
    assert (
        applicability({"vessel_make": "Stabicraft", "vessel_model": ["2050", "1850"]}, prof())
        == "matches"
    )
    assert applicability({"engine_model": ["F150", "F175"]}, prof("Yamaha", "F175")) == "matches"
