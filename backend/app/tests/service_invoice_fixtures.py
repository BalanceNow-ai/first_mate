"""Synthetic invoice documents for the invoice tests (safe, generated, no real data).

``make_pdf`` writes a minimal, valid PDF by hand (Helvetica text objects positioned with
``Tm``) so the ``local_fixture`` extractor reads a real text layer with page coordinates.
``make_png`` writes a tiny deterministic PNG for the image-registry path.
"""

from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass, field

PAGE_W, PAGE_H = 595, 842


@dataclass
class Text:
    text: str
    x: float
    y: float
    size: float = 10


@dataclass
class InvoiceDoc:
    """A synthetic invoice laid out as positioned text (top of page = high ``y``)."""

    header: list[tuple[str, str]] = field(default_factory=list)  # (label, value)
    columns: list[str] = field(
        default_factory=lambda: ["Description", "Part No", "Qty", "Unit", "Unit Price", "Amount"]
    )
    rows: list[list[str]] = field(default_factory=list)
    footer: list[tuple[str, str]] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)  # free text rows after the totals
    second_page: list[str] = field(default_factory=list)

    def pages(self) -> list[list[Text]]:
        items: list[Text] = []
        y = 800.0
        for label, value in self.header:
            items.append(Text(f"{label}: {value}", 50, y))
            y -= 16
        y -= 14
        xs = column_xs(len(self.columns))
        for col, x in zip(self.columns, xs, strict=True):
            items.append(Text(col, x, y))
        y -= 16
        for row in self.rows:
            for cell, x in zip(row, xs, strict=False):
                if cell != "":
                    items.append(Text(cell, x, y))
            y -= 16
        y -= 10
        for label, value in self.footer:
            items.append(Text(f"{label}: {value}", 330, y))
            y -= 16
        y -= 10
        for line in self.extra:
            items.append(Text(line, 50, y, 9))
            y -= 14
        pages = [items]
        if self.second_page:
            pages.append([Text(line, 50, 800 - 16 * i, 9) for i, line in enumerate(self.second_page)])
        return pages


def column_xs(n: int) -> list[float]:
    if n == 6:
        return [50, 230, 330, 370, 420, 500]
    if n == 7:
        return [50, 210, 300, 340, 390, 460, 530]
    step = 480 / max(n, 1)
    return [50 + i * step for i in range(n)]


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[Text]]) -> bytes:
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    pages_id = add(b"")
    kids = []
    for items in pages:
        stream = "".join(
            f"BT /F1 {t.size:g} Tf 1 0 0 1 {t.x:g} {t.y:g} Tm ({_esc(t.text)}) Tj ET\n" for t in items
        ).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>".encode()
            )
        )
    objs[pages_id - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_blank_pdf() -> bytes:
    """A PDF with no text layer (a scan): the extractor must fall back to manual entry."""
    return make_pdf([[]])


def make_png(seed: int = 1, size: int = 8) -> bytes:
    """A tiny deterministic RGB PNG (distinct bytes per ``seed``)."""
    rows = []
    for y in range(size):
        row = bytearray(b"\x00")
        for x in range(size):
            row += bytes(((x * 31 + y * 17 + seed * 53) % 256, (seed * 97) % 256, (x + y) % 256))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def standard_invoice(**overrides) -> InvoiceDoc:
    """Harbour Marine's invoice for the sink-leak job (the worked example, §15)."""
    doc = InvoiceDoc(
        header=[
            ("Supplier", "Harbour Marine Services"),
            ("Invoice No", "INV-1042"),
            ("Date", "2026-10-30"),
            ("Currency", "NZD"),
        ],
        rows=[
            ["Labour - replace hose and clamps", "", "2.5", "hr", "95.00", "237.50"],
            ["Sanitation hose 25mm ID", "SH-25", "1.5", "m", "18.40", "27.60"],
            ["S/S hose clamp 316", "HC-316-32", "4", "ea", "6.50", "26.00"],
            ["Call-out fee", "", "1", "", "85.00", "85.00"],
            ["Consumables / sundries", "", "", "", "", "12.00"],
        ],
        footer=[("Subtotal", "388.10"), ("GST", "58.22"), ("Total", "446.32")],
        extra=["Warranty: 12 months on parts supplied", "Bank account: 12-3456-7890123-00"],
    )
    for key, value in overrides.items():
        setattr(doc, key, value)
    return doc


def standard_pdf(**overrides) -> bytes:
    return make_pdf(standard_invoice(**overrides).pages())


# --------------------------------------------------------------------------- DB/storage helpers
async def make_asset(
    owner_id,
    content: bytes,
    *,
    media_type: str = "application/pdf",
    purpose: str = "invoice",
    job_id=None,
    uploaded_by=None,
    status: str = "available",
    organization_id=None,
):
    """An EvidenceAsset row whose validated bytes are in the configured store (as the media
    workstream leaves it once scanning/decoding has finished)."""
    import hashlib

    from app.database import async_session
    from app.models.service_jobs import EvidenceAsset
    from app.services.service_jobs import storage

    key = storage.new_key("original")
    storage.get_store().put(key, content, media_type)
    async with async_session() as s:
        asset = EvidenceAsset(
            owner_id=owner_id,
            job_id=job_id,
            uploaded_by=uploaded_by or owner_id,
            uploader_organization_id=organization_id,
            purpose=purpose,
            declared_filename="invoice.pdf" if media_type == "application/pdf" else "invoice.png",
            declared_content_type=media_type,
            max_bytes=20 * 1024 * 1024,
            storage_key=key,
            derivative_key=key,
            detected_type=media_type,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            pages=1 if media_type == "application/pdf" else None,
            status=status,
        )
        s.add(asset)
        await s.commit()
        await s.refresh(asset)
        return asset
