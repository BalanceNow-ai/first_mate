"""Upload scanning (SJ-D6, SJ-19). Any scanner failure keeps the upload quarantined.

Backends (``UPLOAD_SCANNER``):

* ``clamd`` — production. Streams the bytes to a clamd daemon with the INSTREAM command
  over TCP, in bounded chunks, with a socket timeout.
* ``local_signature`` — DEVELOPMENT/TEST SUBSTITUTE ONLY. **This is not a malware scanner.**
  It detects the EICAR test string and a few structural red flags (executable headers),
  so the quarantine/reject paths can be exercised without a daemon. Configuration
  validation refuses it outside development/test.
* ``disabled`` — never clears anything: every upload stays quarantined.

``scan`` never raises; it returns ``clean``, ``infected`` or ``error``. Only ``clean``
lets processing continue.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field

from app.config import get_settings

EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
CHUNK_BYTES = 64 * 1024
# Leading bytes of executables a photo/PDF upload must never be.
_EXECUTABLE_MAGIC = {
    b"MZ": "Structural.PE-Executable",
    b"\x7fELF": "Structural.ELF-Executable",
    b"\xcf\xfa\xed\xfe": "Structural.MachO-Executable",
    b"\xca\xfe\xba\xbe": "Structural.MachO-Fat-Executable",
}


@dataclass
class ScanResult:
    status: str  # "clean" | "infected" | "error"
    engine: str
    signature: str | None = None
    detail: str | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {"status": self.status, "engine": self.engine}
        if self.signature:
            out["signature"] = self.signature
        if self.detail:
            out["detail"] = self.detail
        return out


def local_signature(data: bytes) -> ScanResult:
    """Test-only substitute — NOT a malware scanner (see module docstring)."""
    engine = "local_signature (test substitute, not a malware scanner)"
    if EICAR in data:
        return ScanResult("infected", engine, signature="Eicar-Test-Signature")
    for magic, name in _EXECUTABLE_MAGIC.items():
        if data.startswith(magic):
            return ScanResult("infected", engine, signature=name)
    return ScanResult("clean", engine)


def clamd(data: bytes, *, host: str, port: int, timeout: float, chunk_bytes: int = CHUNK_BYTES) -> ScanResult:
    """Scan with clamd INSTREAM. Timeouts, refusals and protocol errors are ``error``."""
    engine = "clamd"
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"zINSTREAM\0")
            for start in range(0, len(data), chunk_bytes):
                chunk = data[start : start + chunk_bytes]
                sock.sendall(struct.pack("!L", len(chunk)) + chunk)
            sock.sendall(struct.pack("!L", 0))
            reply = b""
            while not reply.endswith(b"\0") and len(reply) < 4096:
                part = sock.recv(4096)
                if not part:
                    break
                reply += part
    except TimeoutError:
        return ScanResult("error", engine, detail="timeout")
    except OSError as exc:
        return ScanResult("error", engine, detail=f"connection_failed:{type(exc).__name__}")
    text = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
    # Replies: "stream: OK", "stream: <signature> FOUND", "<message> ERROR".
    if text.endswith(" FOUND"):
        signature = text.removeprefix("stream:").removesuffix(" FOUND").strip()
        return ScanResult("infected", engine, signature=signature[:120] or "unknown")
    if text == "stream: OK":
        return ScanResult("clean", engine)
    return ScanResult("error", engine, detail=("clamd_error:" + text)[:160] if text else "empty_reply")


def scan(data: bytes) -> ScanResult:
    """Scan with the configured backend. Never raises."""
    settings = get_settings()
    backend = settings.upload_scanner
    try:
        if backend == "clamd":
            return clamd(
                data, host=settings.clamd_host, port=settings.clamd_port, timeout=settings.clamd_timeout_seconds
            )
        if backend == "local_signature":
            if not settings.is_local:
                return ScanResult("error", backend, detail="local_signature_refused_outside_development")
            return local_signature(data)
        if backend == "disabled":
            return ScanResult("error", "disabled", detail="scanner_disabled")
        return ScanResult("error", str(backend), detail="unknown_scanner")
    except Exception as exc:  # pragma: no cover - defensive: a scanner bug must not release content
        return ScanResult("error", str(backend), detail=f"scanner_exception:{type(exc).__name__}")
