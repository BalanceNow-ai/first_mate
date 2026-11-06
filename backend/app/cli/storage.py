"""Object-store provisioning for service-job media (local stack: VersityGW)."""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings


def _init(_args) -> int:
    settings = get_settings()
    if settings.object_store_backend == "local_fs":
        Path(settings.object_store_local_path).mkdir(parents=True, exist_ok=True)
        print("storage-init: local_fs directory ready (development/test backend)")
        return 0
    if settings.object_store_backend != "s3":
        print(f"storage-init: unknown OBJECT_STORE_BACKEND {settings.object_store_backend!r}")
        return 1
    from app.services.service_jobs.storage import ObjectStoreError
    from app.services.service_jobs.storage_s3 import S3Store

    try:
        created = S3Store.from_settings(settings).ensure_bucket()
    except ObjectStoreError as exc:
        print(f"storage-init: failed: {exc}")
        return 1
    state = "created" if created else "already present"
    print(f"storage-init: private bucket {settings.object_store_bucket!r} {state}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("storage-init", help="Create the private service-media bucket if missing (idempotent)")
    p.set_defaults(handler=_init)
