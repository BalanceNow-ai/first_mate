"""Media processing: SJ-19 (malware, spoofing, size/pixels/pages, active PDFs, scanner
failure), metadata stripping, HEIC, orientation, quality hints, duplicates."""

from __future__ import annotations

import io
import socket
import struct
import threading
import time
import uuid

import pytest
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import update

from app.config import get_settings
from app.core.errors import AppError
from app.database import async_session
from app.models.service_jobs import EvidenceAsset
from app.services.service_jobs import media, scanner
from app.tests.service_jobs_support import world  # noqa: F401
from app.tests.test_service_media_support import (  # noqa: F401
    EICAR,
    blurry,
    checkerboard,
    dark,
    encode,
    fetch_download,
    jpeg_with_gps,
    load_asset,
    media_env,
    png_bomb_header,
    process,
    put_content,
    scene,
    simple_pdf,
    upload,
)


# --------------------------------------------------------------------------- type detection
def test_detect_type_uses_magic_bytes_only():
    assert media.detect_type(encode(scene(), "JPEG")) == media.JPEG
    assert media.detect_type(encode(scene(), "PNG")) == media.PNG
    assert media.detect_type(encode(scene(), "WEBP")) == media.WEBP
    assert media.detect_type(encode(scene(), "HEIC")) == media.HEIC
    assert media.detect_type(simple_pdf()) == media.PDF
    for spoof in (
        b"<!doctype html><html><script>alert(1)</script></html>",
        b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x00" * 40,
        b"GIF89a\x01\x00\x01\x00",
    ):
        assert media.detect_type(spoof) is None


# --------------------------------------------------------------------------- SJ-19 end to end
@pytest.mark.parametrize(
    ("data_factory", "body", "reason"),
    [
        (lambda: EICAR, {"filename": "photo.jpg", "content_type": "image/jpeg"}, "malware_detected"),
        (
            lambda: b"<html><body><script>alert(document.cookie)</script></body></html>",
            {"filename": "pump.jpg", "content_type": "image/jpeg"},
            "unsupported_type",
        ),
        (
            lambda: b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
            {"filename": "label.png", "content_type": "image/png"},
            "unsupported_type",
        ),
        (
            lambda: b"PK\x03\x04" + b"\x00" * 200,
            {"filename": "hose.webp", "content_type": "image/webp"},
            "unsupported_type",
        ),
        (lambda: b"\xff\xd8\xff\xe0garbage-not-a-jpeg" * 4, {"filename": "x.jpg"}, "malformed_image"),
        (lambda: png_bomb_header(), {"filename": "bomb.png"}, "too_many_pixels"),
        (lambda: simple_pdf(), {"filename": "photo.jpg", "content_type": "image/jpeg"}, "type_not_allowed"),
        (lambda: b"MZ\x90\x00" + b"\x00" * 64, {"filename": "photo.jpg"}, "malware_detected"),
    ],
    ids=["eicar", "html-as-jpg", "svg-as-png", "zip-as-webp", "broken-jpeg", "pixel-bomb", "pdf-as-photo", "exe"],
)
async def test_sj19_hostile_uploads_are_rejected(client, world, media_env, data_factory, body, reason):  # noqa: F811
    asset = await upload(client, world.owner, world.job.id, data_factory(), **body)
    assert asset["status"] == "rejected"
    assert asset["rejection_reason"] == reason
    r = await client.post(f"/api/v1/service-assets/{asset['id']}/download-url", json={}, headers=world.owner.headers)
    assert r.status_code == 409 and r.json()["code"] == "asset_not_available"
    stored = await load_asset(asset["id"])
    assert stored.derivative_key is None
    assert media_env.object_count() == 0  # rejected bytes are not kept


async def test_sj19_mime_spoofing_png_declared_as_pdf_is_detected_as_png(client, world, media_env):  # noqa: F811
    asset = await upload(
        client,
        world.owner,
        world.job.id,
        encode(scene(), "PNG"),
        purpose="job_document",
        filename="invoice.pdf",
        content_type="application/pdf",
    )
    assert asset["status"] == "available"
    assert asset["detected_type"] == "image/png"  # the declared type/extension were ignored


async def test_sj19_pixel_limit_from_settings(client, world, media_env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(get_settings(), "service_image_max_pixels", 100 * 100)
    asset = await upload(client, world.owner, world.job.id, encode(scene((200, 120)), "PNG"))
    assert (asset["status"], asset["rejection_reason"]) == ("rejected", "too_many_pixels")


async def test_sj19_image_type_limit_applies_to_documents(client, world, media_env, monkeypatch):  # noqa: F811
    data = encode(checkerboard((256, 256)), "PNG")
    monkeypatch.setattr(get_settings(), "service_image_max_bytes", len(data) - 1)
    asset = await upload(client, world.owner, world.job.id, data, purpose="job_document")
    assert (asset["status"], asset["rejection_reason"]) == ("rejected", "too_large")


# --------------------------------------------------------------------------- PDFs
def _pdf_cases():
    first_extra = 5  # object number of the first extra object for a one-page PDF
    return {
        "javascript_openaction": simple_pdf(
            catalog_extra=f"/OpenAction {first_extra} 0 R".encode(),
            extra=[b"<< /S /JavaScript /JS (app.alert('hi')) >>"],
        ),
        "openaction_goto": simple_pdf(catalog_extra=b"/OpenAction [4 0 R /Fit]"),
        "names_javascript_hex_escaped": simple_pdf(  # evades a naive byte scan; caught structurally
            catalog_extra=f"/Names << /J#61vaScript {first_extra} 0 R >>".encode(),
            extra=[b"<< /Names [(x) 6 0 R] >>", b"<< /S /J#61vaScript /J#53 (app.alert(1)) >>"],
        ),
        "page_additional_actions": simple_pdf(page_extra=b"/A#41 << /O << /S /GoTo /D [4 0 R /Fit] >> >>"),
        "launch_annotation": simple_pdf(
            page_extra=f"/Annots [{first_extra} 0 R]".encode(),
            extra=[b"<< /Type /Annot /Subtype /Link /Rect [0 0 10 10] /A << /S /L#61unch /F (cmd.exe) >> >>"],
        ),
        "embedded_file": simple_pdf(
            catalog_extra=f"/Names << /Embedded#46iles {first_extra} 0 R >>".encode(),
            extra=[b"<< /Names [(a.exe) << /Type /Filespec /F (a.exe) >>] >>"],
        ),
        "file_attachment_annotation": simple_pdf(
            page_extra=f"/Annots [{first_extra} 0 R]".encode(),
            extra=[b"<< /Type /Annot /Subtype /FileAttachment /Rect [0 0 10 10] /FS (a.exe) >>"],
        ),
        "xfa_form": simple_pdf(catalog_extra=b"/AcroForm << /Fields [] /XF#41 (<xdp/>) >>"),
    }


@pytest.mark.parametrize("case", list(_pdf_cases()))
def test_active_pdfs_are_rejected(case):
    with pytest.raises(media.RejectedError) as exc:
        media.process_pdf(_pdf_cases()[case])
    assert exc.value.code == "active_pdf_content", case


def test_encrypted_malformed_and_too_many_pages(monkeypatch):
    encrypted = simple_pdf(
        trailer_extra=b"/Encrypt 5 0 R /ID [<00112233445566778899aabbccddeeff> <00112233445566778899aabbccddeeff>]",
        extra=[
            b"<< /Filter /Standard /V 1 /R 2 /P -4 "
            b"/O (0123456789abcdef0123456789abcdef) /U (0123456789abcdef0123456789abcdef) >>"
        ],
    )
    with pytest.raises(media.RejectedError) as exc:
        media.process_pdf(encrypted)
    assert exc.value.code == "encrypted_pdf"
    for broken in (b"%PDF-1.7\nthis is not a pdf at all", b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 9 0 R >>\n"):
        with pytest.raises(media.RejectedError) as exc:
            media.process_pdf(broken)
        assert exc.value.code == "malformed_pdf"
    monkeypatch.setattr(get_settings(), "service_pdf_max_pages", 2)
    assert media.process_pdf(simple_pdf(pages=2)).pages == 2
    with pytest.raises(media.RejectedError) as exc:
        media.process_pdf(simple_pdf(pages=3))
    assert exc.value.code == "too_many_pages"


async def test_inert_pdf_invoice_derivative_drops_document_metadata(client, world, media_env):  # noqa: F811
    pdf = simple_pdf(
        trailer_extra=b"/Info 5 0 R",
        extra=[b"<< /Author (Olivia Owner) /Producer (SecretProducer 9.1) /Title (Private) >>"],
    )
    r = await client.post(
        "/api/v1/service-assets/invoice-intents",
        json={"job_id": str(world.job.id), "filename": "invoice.pdf"},
        headers=world.owner.headers,
    )
    assert r.status_code == 201, r.text
    asset_id = r.json()["asset"]["id"]
    assert (await put_content(client, world.owner, asset_id, pdf)).status_code == 202
    assert await process(asset_id) == "available"
    asset = (await client.get(f"/api/v1/service-assets/{asset_id}", headers=world.owner.headers)).json()
    assert (asset["detected_type"], asset["pages"], asset["purpose"]) == ("application/pdf", 1, "invoice")
    got = await fetch_download(client, world.owner, asset_id)
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/pdf"
    assert got.headers["content-disposition"].startswith("attachment;")  # never rendered inline
    assert got.headers["x-content-type-options"] == "nosniff"
    assert b"Olivia" not in got.content and b"SecretProducer" not in got.content
    assert len(PdfReader(io.BytesIO(got.content)).pages) == 1
    original = await fetch_download(client, world.owner, asset_id, "original")
    assert original.content == pdf  # the private original is kept byte-for-byte


async def test_active_pdf_upload_is_rejected_end_to_end(client, world, media_env):  # noqa: F811
    asset = await upload(
        client, world.owner, world.job.id, _pdf_cases()["javascript_openaction"], purpose="job_document"
    )
    assert (asset["status"], asset["rejection_reason"]) == ("rejected", "active_pdf_content")


def _stream(dictionary: bytes, data: bytes) -> bytes:
    return b"<< " + dictionary + b" /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream"


XMP = (
    b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
    b"<rdf:RDF><rdf:Description exif:GPSLatitude='36,51S'/></rdf:RDF></x:xmpmeta><?xpacket end='w'?>"
)


def pdf_with_photo_metadata() -> bytes:
    """A scanned-photo style PDF whose embedded JPEGs carry EXIF/GPS (page image, an image in
    a form XObject, and an inline image) plus XMP on the catalog and on the image."""
    leak = jpeg_with_gps((16, 16), orientation=1)
    assert b"Exif" in leak and b"SecretCam" in leak
    content = b"q 64 0 0 64 0 0 cm /Im0 Do Q q /Fm0 Do Q q 8 0 0 8 0 0 cm BI /W 16 /H 16 /CS /RGB /BPC 8 /F /DCT ID "
    content += leak + b" EI Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /Metadata 7 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 64 64] "
        b"/Resources << /XObject << /Im0 4 0 R /Fm0 6 0 R >> >> /Contents 5 0 R >>",
        _stream(
            b"/Type /XObject /Subtype /Image /Width 16 /Height 16 /ColorSpace /DeviceRGB /BitsPerComponent 8 "
            b"/Filter /DCTDecode /Metadata 7 0 R",
            leak,
        ),
        _stream(b"", content),
        _stream(
            b"/Type /XObject /Subtype /Form /BBox [0 0 64 64] /Resources << /XObject << /Im1 8 0 R >> >>",
            b"q 32 0 0 32 0 0 cm /Im1 Do Q",
        ),
        _stream(b"/Type /Metadata /Subtype /XML", XMP),
        _stream(
            b"/Type /XObject /Subtype /Image /Width 16 /Height 16 /ColorSpace /DeviceRGB /BitsPerComponent 8 "
            b"/Filter [/DCTDecode]",
            leak,
        ),
    ]
    from app.tests.test_service_media_support import build_pdf

    return build_pdf(objects)


def test_pdf_derivative_carries_no_embedded_image_exif_or_xmp():
    """Review finding (p6): PDF derivatives kept embedded JPEGs byte-for-byte, EXIF/GPS included."""
    pdf = pdf_with_photo_metadata()
    out = media.process_pdf(pdf)
    assert out.status == "available" and out.pages == 1
    for marker in (b"Exif", b"SecretCam", b"OwnerPhoneSoftware", b"xmpmeta", b"xpacket", b"GPSLatitude"):
        assert marker not in out.derivative, marker
    reader = PdfReader(io.BytesIO(out.derivative))
    page = reader.pages[0]
    images = page.images  # XObject images (incl. the form's) and the inline one still render
    assert len(images) >= 3
    for image in images:
        assert image.image.size == (16, 16)
        assert not image.image.getexif()
    assert "/Metadata" not in reader.trailer["/Root"]


async def test_pdf_document_shared_with_the_contractor_has_no_photo_metadata(client, world, media_env):  # noqa: F811
    asset = await upload(client, world.owner, world.job.id, pdf_with_photo_metadata(), purpose="job_document")
    assert asset["status"] == "available", asset
    for actor in (world.owner, world.tech):
        got = await fetch_download(client, actor, asset["id"])
        assert got.status_code == 200
        assert b"Exif" not in got.content and b"SecretCam" not in got.content and b"xmpmeta" not in got.content


# --------------------------------------------------------------------------- images: metadata, orientation, HEIC
async def test_exif_and_gps_are_removed_from_the_derivative(client, world, media_env):  # noqa: F811
    original_bytes = jpeg_with_gps((40, 20), orientation=6)
    assert Image.open(io.BytesIO(original_bytes)).getexif().get_ifd(0x8825)  # the source has GPS
    asset = await upload(client, world.owner, world.job.id, original_bytes)
    assert asset["status"] == "available"
    # Orientation 6 (rotate 90°) was applied: 40×20 becomes 20×40.
    assert (asset["width"], asset["height"]) == (20, 40)
    got = await fetch_download(client, world.owner, asset["id"])
    derived = Image.open(io.BytesIO(got.content))
    assert derived.format == "JPEG" and derived.size == (20, 40)
    assert len(derived.getexif()) == 0
    assert "exif" not in derived.info and "icc_profile" not in derived.info
    for marker in (b"Exif", b"SecretCam", b"OwnerPhoneSoftware", b"GPS"):
        assert marker not in got.content
    # The contractor gets the same stripped derivative and cannot ask for the original.
    got_tech = await fetch_download(client, world.tech, asset["id"])
    assert got_tech.content == got.content
    r = await client.post(
        f"/api/v1/service-assets/{asset['id']}/download-url", json={"variant": "original"}, headers=world.tech.headers
    )
    assert r.status_code == 403
    original = await fetch_download(client, world.owner, asset["id"], "original")
    assert original.content == original_bytes


async def test_heic_is_converted_to_a_jpeg_derivative(client, world, media_env):  # noqa: F811
    asset = await upload(client, world.owner, world.job.id, encode(scene((64, 48)), "HEIC"), filename="IMG_0001.HEIC")
    assert asset["status"] == "available", asset
    assert asset["detected_type"] == "image/heic"
    assert (asset["width"], asset["height"]) == (64, 48)
    got = await fetch_download(client, world.owner, asset["id"])
    img = Image.open(io.BytesIO(got.content))
    assert img.format == "JPEG" and img.size == (64, 48)
    r, g, b = img.getpixel((55, 42))  # inside the yellow ellipse
    assert r > 180 and g > 180 and b < 120


async def test_webp_and_png_alpha_are_accepted(client, world, media_env):  # noqa: F811
    for data in (encode(scene(), "WEBP"), encode(scene().convert("RGBA"), "PNG")):
        asset = await upload(client, world.owner, world.job.id, data)
        assert asset["status"] == "available"


# --------------------------------------------------------------------------- capture quality
async def test_capture_quality_hints_are_advisory_and_never_invent_text(client, world, media_env):  # noqa: F811
    sharp = await upload(client, world.owner, world.job.id, encode(checkerboard(), "JPEG", quality=95))
    soft = await upload(client, world.owner, world.job.id, blurry())
    gloomy = await upload(client, world.owner, world.job.id, dark())
    assert sharp["quality"]["blur"] == "ok" and sharp["quality"]["darkness"] == "ok"
    assert soft["quality"]["blur"] == "blurry"
    assert gloomy["quality"]["darkness"] == "dark"
    for asset in (sharp, soft, gloomy):
        q = asset["quality"]
        assert q["framing"] == "not_assessed" and q["label_legibility"] == "not_assessed"
        assert "phash" not in q  # internal fingerprint is not exposed
        assert not any("text" in k for k in q)


# --------------------------------------------------------------------------- duplicates
async def test_exact_and_perceptual_duplicates_are_flagged(client, world, media_env):  # noqa: F811
    img = scene()
    first = await upload(client, world.owner, world.job.id, encode(img, "JPEG", quality=95))
    exact = await upload(client, world.owner, world.job.id, encode(img, "JPEG", quality=95))
    reencoded = await upload(client, world.owner, world.job.id, encode(img, "PNG"))
    different = await upload(client, world.owner, world.job.id, encode(checkerboard(), "JPEG"))
    assert first["duplicate_of_id"] is None
    assert exact["duplicate_of_id"] == first["id"]
    assert reencoded["duplicate_of_id"] == first["id"]
    assert different["duplicate_of_id"] is None
    # A duplicate in another owner's job is not a duplicate here (job-scoped).
    other = await upload(client, world.other_owner, world.other_job.id, encode(img, "JPEG", quality=95))
    assert other["duplicate_of_id"] is None


# --------------------------------------------------------------------------- scanners
class FakeClamd:
    """A minimal clamd speaking zINSTREAM over TCP, for contract tests."""

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.chunks: list[int] = []
        self.received = b""
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _read_exact(self, conn, n):
        buf = b""
        while len(buf) < n:
            part = conn.recv(n - len(buf))
            if not part:
                raise ConnectionError
            buf += part
        return buf

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    assert self._read_exact(conn, 10) == b"zINSTREAM\0"
                    while True:
                        (size,) = struct.unpack("!L", self._read_exact(conn, 4))
                        if size == 0:
                            break
                        self.chunks.append(size)
                        self.received += self._read_exact(conn, size)
                    if self.mode == "hang":
                        time.sleep(1.5)
                        continue
                    reply = {
                        "ok": b"stream: OK\0",
                        "found": b"stream: Win.Test.EICAR_HDB-1 FOUND\0",
                        "error": b"INSTREAM size limit exceeded. ERROR\0",
                    }[self.mode]
                    conn.sendall(reply)
                except (ConnectionError, OSError, AssertionError):
                    continue

    def close(self):
        self._stop = True
        self.sock.close()


def test_clamd_instream_contract():
    data = bytes(range(256)) * 1000  # 256 000 bytes → several chunks
    for mode, expected in (("ok", "clean"), ("found", "infected"), ("error", "error")):
        server = FakeClamd(mode)
        try:
            result = scanner.clamd(data, host="127.0.0.1", port=server.port, timeout=2.0, chunk_bytes=65536)
        finally:
            server.close()
        assert result.status == expected, (mode, result)
        assert server.received == data
        assert max(server.chunks) <= 65536 and len(server.chunks) == 4
    assert scanner.clamd(b"x", host="127.0.0.1", port=server.port, timeout=0.5).status == "error"  # refused
    hang = FakeClamd("hang")
    try:
        result = scanner.clamd(b"abc", host="127.0.0.1", port=hang.port, timeout=0.3)
    finally:
        hang.close()
    assert (result.status, result.detail) == ("error", "timeout")
    found = FakeClamd("found")
    try:
        assert scanner.clamd(EICAR, host="127.0.0.1", port=found.port, timeout=2).signature == "Win.Test.EICAR_HDB-1"
    finally:
        found.close()


def test_local_signature_is_refused_outside_development(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_scanner", "local_signature")
    assert scanner.scan(EICAR).status == "infected"
    monkeypatch.setattr(settings, "app_env", "production")
    assert scanner.scan(b"harmless").status == "error"
    assert "not a malware scanner" in scanner.local_signature(b"x").engine


@pytest.mark.parametrize("mode", ["disabled", "clamd_timeout", "clamd_down", "clamd_error"])
async def test_sj19_scanner_failure_leaves_the_upload_quarantined(client, world, media_env, monkeypatch, mode):  # noqa: F811
    settings = get_settings()
    server = None
    if mode == "disabled":
        monkeypatch.setattr(settings, "upload_scanner", "disabled")
    else:
        monkeypatch.setattr(settings, "upload_scanner", "clamd")
        monkeypatch.setattr(settings, "clamd_host", "127.0.0.1")
        monkeypatch.setattr(settings, "clamd_timeout_seconds", 0.3)
        if mode == "clamd_down":
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            monkeypatch.setattr(settings, "clamd_port", probe.getsockname()[1])
            probe.close()
        else:
            server = FakeClamd("hang" if mode == "clamd_timeout" else "error")
            monkeypatch.setattr(settings, "clamd_port", server.port)
    try:
        asset = await upload(client, world.owner, world.job.id, encode(scene(), "JPEG"))
        assert asset["status"] == "quarantined"
        # Retries (while attempts remain) never release it either.
        for _ in range(settings.service_processing_max_attempts + 1):
            await process(asset["id"])
        stored = await load_asset(asset["id"])
        assert stored.status == "quarantined" and stored.derivative_key is None
        assert stored.scan_result["status"] == "error"
        assert stored.attempts == settings.service_processing_max_attempts
        r = await client.post(f"/api/v1/service-assets/{asset['id']}/download-url", headers=world.owner.headers)
        assert r.status_code == 409
        r = await client.get(f"/api/v1/service-jobs/{world.job.id}/assets", headers=world.tech.headers)
        assert r.json()["items"] == []
    finally:
        if server:
            server.close()


async def test_clamd_clean_result_releases_the_upload(client, world, media_env, monkeypatch):  # noqa: F811
    settings = get_settings()
    server = FakeClamd("ok")
    monkeypatch.setattr(settings, "upload_scanner", "clamd")
    monkeypatch.setattr(settings, "clamd_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamd_port", server.port)
    try:
        asset = await upload(client, world.owner, world.job.id, encode(scene(), "JPEG"))
    finally:
        server.close()
    assert asset["status"] == "available"
    stored = await load_asset(asset["id"])
    assert stored.scan_result == {"status": "clean", "engine": "clamd"}


async def test_integrity_mismatch_is_rejected(client, world, media_env):  # noqa: F811
    r = await client.post(f"/api/v1/service-jobs/{world.job.id}/assets/intents", json={}, headers=world.owner.headers)
    asset_id = r.json()["asset"]["id"]
    await put_content(client, world.owner, asset_id, encode(scene(), "JPEG"))
    stored = await load_asset(asset_id)
    media_env.store.put(stored.storage_key, encode(checkerboard(), "JPEG"), "application/octet-stream")
    assert await process(asset_id) == "rejected"
    assert (await load_asset(asset_id)).rejection_reason == "integrity_mismatch"


async def test_derivative_bytes_only_for_available_assets(client, world, media_env):  # noqa: F811
    asset = await upload(client, world.owner, world.job.id, jpeg_with_gps())
    async with async_session() as s:
        row = await s.get(EvidenceAsset, uuid.UUID(asset["id"]))
        data = await media.derivative_bytes(s, row)
        assert media.derivative_media_type(row) == "image/jpeg"
        assert b"GPS" not in data and b"SecretCam" not in data
        await s.execute(update(EvidenceAsset).where(EvidenceAsset.id == row.id).values(status="rejected"))
        await s.commit()
        with pytest.raises(AppError):
            await media.derivative_bytes(s, row)
