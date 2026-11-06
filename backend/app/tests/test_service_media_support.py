"""Shared fixtures and synthetic media for the private-media tests (no tests here).

Every image and PDF is generated in-process: Pillow/pillow-heif images (one carrying GPS
EXIF and an orientation tag) and hand-written PDF bytes with correct xref offsets.
"""

from __future__ import annotations

import io
import struct
import uuid
import zlib
from dataclasses import dataclass, field

import pillow_heif
import pytest
from PIL import Image, ImageDraw, ImageFilter
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session
from app.models.service_jobs import EvidenceAsset
from app.services.service_jobs import media, storage

pillow_heif.register_heif_opener()


# --------------------------------------------------------------------------- environment
@dataclass
class MediaEnv:
    root: str
    queued: list[uuid.UUID] = field(default_factory=list)

    @property
    def store(self) -> storage.LocalFsStore:
        return storage.get_store()

    def object_count(self) -> int:
        import os

        return sum(len(files) for _, _, files in os.walk(self.root))


@pytest.fixture
def media_env(tmp_path, monkeypatch) -> MediaEnv:
    """local_fs store in a tmp dir, the test-only signature scanner, and processing
    captured instead of queued (tests run it explicitly)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "object_store_backend", "local_fs")
    monkeypatch.setattr(settings, "object_store_local_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "upload_scanner", "local_signature")
    env = MediaEnv(str(tmp_path / "store"))
    storage.set_store(storage.LocalFsStore(env.root))
    monkeypatch.setattr(media, "enqueue_processing", lambda asset_id: env.queued.append(asset_id) or True)
    yield env
    storage.set_store(None)


async def process(asset_id) -> str:
    async with async_session() as s:
        return await media.process_asset(s, uuid.UUID(str(asset_id)))


async def load_asset(asset_id) -> EvidenceAsset:
    async with async_session() as s:
        return (await s.execute(select(EvidenceAsset).where(EvidenceAsset.id == uuid.UUID(str(asset_id))))).scalar_one()


# --------------------------------------------------------------------------- API helpers
async def job_intent(client, actor, job_id, *, headers=None, **body):
    body.setdefault("purpose", "job_photo")
    return await client.post(
        f"/api/v1/service-jobs/{job_id}/assets/intents", json=body, headers={**actor.headers, **(headers or {})}
    )


async def put_content(client, actor, asset_id, data: bytes, content_type: str = "application/octet-stream"):
    return await client.put(
        f"/api/v1/service-assets/{asset_id}/content",
        content=data,
        headers={**actor.headers, "Content-Type": content_type},
    )


async def upload(client, actor, job_id, data: bytes, *, run: bool = True, **body) -> dict:
    """Intent → content → (optionally) processing. Returns the asset JSON."""
    r = await job_intent(client, actor, job_id, **body)
    assert r.status_code == 201, r.text
    asset_id = r.json()["asset"]["id"]
    r = await put_content(client, actor, asset_id, data)
    assert r.status_code == 202, r.text
    if run:
        await process(asset_id)
    r = await client.get(f"/api/v1/service-assets/{asset_id}", headers=actor.headers)
    assert r.status_code == 200, r.text
    return r.json()


async def fetch_download(client, actor, asset_id, variant: str = "derivative"):
    r = await client.post(
        f"/api/v1/service-assets/{asset_id}/download-url", json={"variant": variant}, headers=actor.headers
    )
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    return await client.get(url)


# --------------------------------------------------------------------------- synthetic images
def checkerboard(size=(256, 256), square=8, colors=((20, 20, 20), (235, 235, 235))) -> Image.Image:
    img = Image.new("RGB", size, colors[0])
    draw = ImageDraw.Draw(img)
    for y in range(0, size[1], square):
        for x in range(0, size[0], square):
            if (x // square + y // square) % 2:
                draw.rectangle([x, y, x + square - 1, y + square - 1], fill=colors[1])
    return img


def scene(size=(256, 192)) -> Image.Image:
    """A structured synthetic 'photo' (gradient + shapes) with a stable perceptual hash."""
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = (x * 255 // size[0], y * 255 // size[1], 128)
    draw = ImageDraw.Draw(img)
    draw.ellipse([30, 30, 120, 120], fill=(250, 250, 20))
    draw.rectangle([150, 60, 230, 170], fill=(10, 40, 200))
    return img


def encode(img: Image.Image, fmt: str = "JPEG", **kw) -> bytes:
    buf = io.BytesIO()
    if fmt == "HEIC":
        pillow_heif.from_pillow(img).save(buf, quality=kw.pop("quality", 70))
    else:
        img.save(buf, fmt, **kw)
    return buf.getvalue()


def jpeg_with_gps(size=(40, 20), orientation: int = 6) -> bytes:
    img = scene(size)
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = "SecretCam"  # Make
    exif[0x0131] = "OwnerPhoneSoftware"  # Software
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "S", (36.0, 50.0, 30.0), "E", (174.0, 45.0, 0.0)
    return encode(img, "JPEG", exif=exif.tobytes(), quality=95)


def blurry() -> bytes:
    return encode(checkerboard().filter(ImageFilter.GaussianBlur(10)), "JPEG", quality=95)


def dark() -> bytes:
    return encode(checkerboard(colors=((2, 2, 2), (30, 30, 30))), "JPEG", quality=95)


def png_bomb_header(width=100_000, height=100_000) -> bytes:
    """A tiny PNG whose header declares 10^10 pixels (decompression bomb)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00" * 1024)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


EICAR = media.scanner.EICAR


# --------------------------------------------------------------------------- hand-written PDFs
def build_pdf(objects: list[bytes], *, trailer_extra: bytes = b"") -> bytes:
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R ".encode() + trailer_extra + b" >>\n"
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def simple_pdf(
    pages: int = 1,
    *,
    catalog_extra: bytes = b"",
    page_extra: bytes = b"",
    extra: list[bytes] = (),
    trailer_extra: bytes = b"",
) -> bytes:
    """Objects: 1 catalog, 2 page tree, 3 content stream, 4.. pages, then ``extra``
    (the first extra object is number ``4 + pages``)."""
    content = b"BT /F1 12 Tf 72 720 Td (Invoice 42: hose clamps) Tj ET"
    kids = " ".join(f"{4 + i} 0 R" for i in range(pages))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R " + catalog_extra + b" >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ]
    for _ in range(pages):
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 3 0 R " + page_extra + b" >>")
    objects.extend(extra)
    return build_pdf(objects, trailer_extra=trailer_extra)
