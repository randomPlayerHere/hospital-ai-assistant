"""Virus-scan hook. Register scanners returning a threat name (or None if clean)."""

import logging
import socket
import struct
from collections.abc import Callable

from app.core.config import get_settings

log = logging.getLogger("app.scan")

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

Scanner = Callable[[bytes], str | None]


def eicar_scanner(data: bytes) -> str | None:
    return "EICAR-Test-File" if EICAR in data else None


def clamav_scanner(data: bytes) -> str | None:
    """Scan data using a ClamAV clamd daemon over TCP via the INSTREAM protocol."""
    s = get_settings()
    if not s.clamav_host:
        return None

    try:
        with socket.create_connection(
            (s.clamav_host, s.clamav_port), timeout=s.clamav_timeout
        ) as sock:
            # Send INSTREAM command
            sock.sendall(b"zINSTREAM\x00")

            # Stream chunks (up to 8192 bytes)
            chunk_size = 8192
            for i in range(0, len(data), chunk_size):
                chunk = data[i : i + chunk_size]
                header = struct.pack(">I", len(chunk))
                sock.sendall(header + chunk)

            # Send 4-byte 0 length terminator
            sock.sendall(struct.pack(">I", 0))

            # Read response
            response = b""
            while True:
                part = sock.recv(1024)
                if not part:
                    break
                response += part
                if b"\x00" in part or b"\n" in part:
                    break

            resp_str = response.decode("utf-8", errors="ignore").strip().rstrip("\x00")
            if "FOUND" in resp_str:
                # Format is typically "stream: <VirusName> FOUND"
                threat = resp_str.split("FOUND")[0].replace("stream:", "").strip()
                return threat or "Threat Detected"
            return None
    except Exception as exc:
        log.warning("ClamAV scan error connecting to %s:%s: %s", s.clamav_host, s.clamav_port, exc)
        return None


SCANNERS: list[Scanner] = [eicar_scanner, clamav_scanner]


def scan(data: bytes) -> str | None:
    for scanner in SCANNERS:
        threat = scanner(data)
        if threat:
            return threat
    return None
