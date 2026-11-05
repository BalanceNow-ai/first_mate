"""Embedding providers for the knowledge corpus.

* ``openai``     — ``settings.openai_embedding_model`` through the OpenAI SDK (batched,
                   with a request timeout). Requires ``OPENAI_API_KEY``.
* ``local_hash`` — a deterministic, offline feature-hashing embedder (word + bigram
                   features, L2-normalised, 1536 dimensions). It is a test/local
                   substitute only: ``Settings.validate_runtime`` refuses it outside
                   ``development``/``test`` and :func:`get_embedder` refuses it too.
* ``disabled``   — ingestion and retrieval are unavailable.

Every chunk records the ``model_id`` of the embedder that produced its vector and
retrieval only compares chunks embedded with the active model.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter
from typing import Protocol

from app.config import Settings, get_settings
from app.core.errors import AppError
from app.models.ai import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)

LOCAL_HASH_MODEL_ID = "local_hash-v1"

# Common English function words carry no topical signal for the hashing embedder.
_STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been before being
    below between both but by can could did do does doing down during each few for from further
    had has have having he her here hers him his how i if in into is it its itself just me more
    most my no nor not now of off on once only or other our ours out over own same she should so
    some such than that the their theirs them then there these they this those through to too
    under until up very was we were what when where which while who whom why will with would you
    your yours""".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")


class EmbeddingsUnavailableError(AppError):
    def __init__(self, message: str = "The knowledge service is not configured") -> None:
        super().__init__(503, "knowledge_unavailable", message)


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _stem(token: str) -> str:
    """Very light plural folding (plugs → plug, batteries → battery)."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lower-case alphanumeric tokens without stopwords (shared with the extractive answerer)."""
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


class LocalHashEmbedder:
    """Deterministic feature hashing: unigram + bigram features, sublinear TF, L2-normalised."""

    model_id = LOCAL_HASH_MODEL_ID

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        return value % self.dimensions, (1.0 if (value >> 63) & 1 else -1.0)

    def embed_one(self, text: str) -> list[float]:
        tokens = tokenize(text)
        features: Counter[str] = Counter(f"w:{t}" for t in tokens)
        features.update(f"b:{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False))
        vector = [0.0] * self.dimensions
        for feature, count in features.items():
            index, sign = self._bucket(feature)
            weight = 1.0 + math.log(count)
            if feature.startswith("b:"):
                weight *= 0.7
            vector[index] += sign * weight
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


def _default_openai_client(settings: Settings):  # pragma: no cover - replaced in tests
    from openai import AsyncOpenAI

    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.ai_request_timeout_seconds,
        max_retries=2,
    )


# Indirection so tests can substitute a fake client at the SDK boundary.
openai_client_factory = _default_openai_client


class OpenAIEmbedder:
    def __init__(self, settings: Settings, client=None) -> None:
        self.model_id = settings.openai_embedding_model
        self.dimensions = settings.embedding_dimensions
        self._settings = settings
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = openai_client_factory(self._settings)
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        batch_size = max(1, self._settings.embedding_batch_size)
        out: list[list[float]] = []
        kwargs = {}
        if self.model_id.startswith("text-embedding-3"):
            kwargs["dimensions"] = self.dimensions
        for start in range(0, len(texts), batch_size):
            batch = [t.replace("\n", " ")[:24_000] for t in texts[start : start + batch_size]]
            try:
                response = await self.client.embeddings.create(
                    model=self.model_id,
                    input=batch,
                    timeout=self._settings.ai_request_timeout_seconds,
                    **kwargs,
                )
            except Exception as exc:  # provider failure: log the type only
                logger.error("Embedding provider error: %s", type(exc).__name__)
                raise AppError(
                    503, "knowledge_unavailable", "The knowledge service is temporarily unavailable"
                ) from None
            vectors = [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
            if len(vectors) != len(batch) or any(len(v) != self.dimensions for v in vectors):
                logger.error("Embedding provider returned an unexpected shape")
                raise AppError(
                    503, "knowledge_unavailable", "The knowledge service is temporarily unavailable"
                )
            out.extend(list(v) for v in vectors)
        return out


def embeddings_available(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if settings.embedding_dimensions != EMBEDDING_DIMENSIONS:
        return False
    if settings.embedding_provider == "openai":
        return bool(settings.openai_api_key)
    if settings.embedding_provider == "local_hash":
        return settings.is_local
    return False


def get_embedder(settings: Settings | None = None) -> EmbeddingProvider:
    """Return the active embedder or raise ``EmbeddingsUnavailableError`` (HTTP 503)."""
    settings = settings or get_settings()
    if not embeddings_available(settings):
        raise EmbeddingsUnavailableError()
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(settings)
    return LocalHashEmbedder(settings.embedding_dimensions)


def active_model_id(settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    if not embeddings_available(settings):
        return None
    return (
        settings.openai_embedding_model
        if settings.embedding_provider == "openai"
        else LOCAL_HASH_MODEL_ID
    )
