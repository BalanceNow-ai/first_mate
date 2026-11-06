"""S3 backend against a real S3-compatible gateway (VersityGW, as in the local stack).

Skipped unless ``OBJECT_STORE_TEST_URL`` points at a reachable gateway, e.g.::

    docker run -d --rm --name sj-objectstore-test -p 127.0.0.1:17070:7070 \\
        versity/versitygw:v1.0.14 --access testkey --secret testsecret posix /tmp
    OBJECT_STORE_TEST_URL=http://127.0.0.1:17070 OBJECT_STORE_TEST_ACCESS_KEY=testkey \\
        OBJECT_STORE_TEST_SECRET_KEY=testsecret python -m pytest app/tests/test_service_media_s3.py

Optionally ``OBJECT_STORE_TEST_PUBLIC_URL`` names a reverse proxy in front of the gateway
(the local stack's nginx on :18080) to prove browser-facing signed URLs verify through it.
"""

from __future__ import annotations

import io
import os
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from PIL import Image

from app.services.service_jobs import storage
from app.services.service_jobs.storage_s3 import S3Store
from app.tests.service_jobs_support import world  # noqa: F401
from app.tests.test_service_media_support import jpeg_with_gps, media_env, upload  # noqa: F401

URL = os.environ.get("OBJECT_STORE_TEST_URL", "")
PUBLIC_URL = os.environ.get("OBJECT_STORE_TEST_PUBLIC_URL", "")
ACCESS = os.environ.get("OBJECT_STORE_TEST_ACCESS_KEY", "testkey")
SECRET = os.environ.get("OBJECT_STORE_TEST_SECRET_KEY", "testsecret")


def _reachable(url: str) -> bool:
    if not url:
        return False
    try:
        httpx.get(url, timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(URL), reason="OBJECT_STORE_TEST_URL unset or unreachable")


def _store(bucket: str, public: str | None = None) -> S3Store:
    return S3Store(
        bucket=bucket,
        endpoint_url=URL,
        public_endpoint_url=public or URL,
        region="us-east-1",
        access_key=ACCESS,
        secret_key=SECRET,
    )


@pytest.fixture
def bucket() -> str:
    return f"sjtest-{uuid.uuid4().hex[:12]}"


def test_s3_store_contract(bucket):
    store = _store(bucket)
    assert store.ensure_bucket() is True
    assert store.ensure_bucket() is False  # idempotent
    key = storage.new_key("derived")
    assert not store.exists(key)
    store.put(key, b"\xff\xd8\xffhello", "image/jpeg")
    assert store.exists(key) and store.get(key) == b"\xff\xd8\xffhello"
    url = store.signed_get_url(key, filename="photo.jpg", content_type="image/jpeg", seconds=3600)
    assert parse_qs(urlparse(url).query)["X-Amz-Expires"] == ["300"]
    got = httpx.get(url)
    assert got.status_code == 200 and got.content == b"\xff\xd8\xffhello"
    assert got.headers["content-disposition"].startswith("attachment")
    assert got.headers.get("cache-control") == "no-store"
    # Unsigned or tampered requests are refused by the gateway (the bucket is private).
    assert httpx.get(f"{URL}/{bucket}/{key}").status_code in (400, 403)
    assert httpx.get(url.replace("X-Amz-Signature=", "X-Amz-Signature=0")).status_code in (400, 403)
    # An expired signature is refused.
    short = store.signed_get_url(key, filename="photo.jpg", content_type="image/jpeg", seconds=1)
    time.sleep(2.2)
    assert httpx.get(short).status_code in (400, 403)
    store.delete(key)
    store.delete(key)  # idempotent
    assert not store.exists(key)
    with pytest.raises(storage.ObjectStoreError):
        store.get(key)


@pytest.mark.skipif(not _reachable(PUBLIC_URL), reason="OBJECT_STORE_TEST_PUBLIC_URL unset or unreachable")
def test_signed_url_verifies_through_the_public_proxy():
    store = _store("helm-private", public=PUBLIC_URL)
    store.ensure_bucket()
    key = storage.new_key("derived")
    store.put(key, b"through-the-proxy", "image/jpeg")
    url = store.signed_get_url(key, filename="photo.jpg", content_type="image/jpeg", seconds=60)
    assert url.startswith(PUBLIC_URL)
    got = httpx.get(url)
    assert got.status_code == 200 and got.content == b"through-the-proxy"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert httpx.put(url, content=b"x").status_code in (403, 405)
    store.delete(key)


async def test_upload_flow_end_to_end_on_s3(client, world, media_env, bucket):  # noqa: F811
    store = _store(bucket)
    store.ensure_bucket()
    storage.set_store(store)
    asset = await upload(client, world.owner, world.job.id, jpeg_with_gps())
    assert asset["status"] == "available"
    r = await client.post(f"/api/v1/service-assets/{asset['id']}/download-url", headers=world.tech.headers)
    assert r.status_code == 200
    got = httpx.get(r.json()["url"])
    assert got.status_code == 200
    derived = Image.open(io.BytesIO(got.content))
    assert derived.format == "JPEG" and len(derived.getexif()) == 0 and b"GPS" not in got.content
    assert (
        await client.delete(f"/api/v1/service-assets/{asset['id']}", headers=world.owner.headers)
    ).status_code == 204
    assert httpx.get(r.json()["url"]).status_code == 404  # objects removed
