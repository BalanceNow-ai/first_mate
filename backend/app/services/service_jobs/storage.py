"""Private object storage for service-job media (SJ-D5).

Interface used by every capability: ``put``/``get``/``delete``/``exists`` on opaque keys and
``signed_get_url`` (≤ ``SIGNED_URL_SECONDS``). Keys are random and never derived from user
input; they are never returned by the API.

Backends: ``s3`` (any private S3-compatible bucket — production, and VersityGW in the local
stack) and ``local_fs`` (development/test only; refused outside them by configuration
validation). The media workstream owns the S3 backend and the download endpoint that
serves ``local_fs`` signed URLs.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from app.config import get_settings


class ObjectStoreError(Exception):
    """Storage failure; callers keep the asset quarantined/unavailable."""


class ObjectStore(Protocol):
    name: str

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def signed_get_url(self, key: str, *, filename: str, content_type: str, seconds: int) -> str: ...


def new_key(prefix: str) -> str:
    """An unguessable object key under a fixed prefix (``quarantine/``, ``original/``, ``derived/``)."""
    return f"{prefix.strip('/')}/{secrets.token_urlsafe(24)}"


class LocalFsStore:
    """Development/test backend. Signed URLs point at the API's token-checked download route."""

    name = "local_fs"

    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if ".." in key.split("/") or key.startswith("/"):
            raise ObjectStoreError("invalid key")
        return self.root / key

    def put(self, key: str, data: bytes, content_type: str) -> None:  # noqa: ARG002
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise ObjectStoreError("missing object") from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def signed_get_url(self, key: str, *, filename: str, content_type: str, seconds: int) -> str:
        expires = int(time.time()) + min(seconds, MAX_SIGNED_URL_SECONDS)
        token = sign_local(key, expires, filename, content_type)
        settings = get_settings()
        query = urlencode({"k": key, "e": expires, "n": filename, "c": content_type, "t": token})
        return f"{settings.api_v1_prefix}/service-assets/local-download?{query}"


# Spec §12: signed URLs live at most five minutes, whatever the configuration says.
MAX_SIGNED_URL_SECONDS = 300


def sign_local(key: str, expires: int, filename: str, content_type: str) -> str:
    secret = get_settings().secret_key.encode()
    msg = f"local-download\n{key}\n{expires}\n{filename}\n{content_type}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def verify_local(key: str, expires: int, filename: str, content_type: str, token: str) -> bool:
    """Constant-time check of a local_fs download token and its expiry."""
    if expires < int(time.time()):
        return False
    return hmac.compare_digest(sign_local(key, expires, filename, content_type), token)


_store: ObjectStore | None = None


def get_store() -> ObjectStore:
    """The configured store (cached). Tests may call ``set_store`` with a fake."""
    global _store
    if _store is None:
        settings = get_settings()
        if settings.object_store_backend == "local_fs":
            _store = LocalFsStore(settings.object_store_local_path)
        elif settings.object_store_backend == "s3":
            from app.services.service_jobs.storage_s3 import S3Store  # media workstream

            _store = S3Store.from_settings(settings)
        else:
            raise ObjectStoreError(f"unknown object store backend {settings.object_store_backend}")
    return _store


def set_store(store: ObjectStore | None) -> None:
    global _store
    _store = store
