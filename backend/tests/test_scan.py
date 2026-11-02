import socket
import socketserver
import struct
import threading
import pytest

from app.core.config import get_settings
from app.services.scan import EICAR, clamav_scanner, eicar_scanner, scan
from tests.conftest import login_headers
from tests.helpers import by_email

CLEAN_PDF = b"%PDF-1.4\n%clean pdf\n" + b"0" * 100
VIRUS_PAYLOAD = b"%PDF-1.4\n" + b"TEST_VIRUS" + b"0" * 100


class _MockClamDHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        cmd = b""
        while not cmd.endswith(b"\x00"):
            b = self.request.recv(1)
            if not b:
                return
            cmd += b

        # Stream reading
        received_data = b""
        while True:
            raw_len = self.request.recv(4)
            if len(raw_len) < 4:
                break
            chunk_len = struct.unpack(">I", raw_len)[0]
            if chunk_len == 0:
                break
            chunk = b""
            while len(chunk) < chunk_len:
                part = self.request.recv(chunk_len - len(chunk))
                if not part:
                    break
                chunk += part
            received_data += chunk

        if b"TEST_VIRUS" in received_data:
            self.request.sendall(b"stream: Win.Test.CustomVirus FOUND\x00")
        else:
            self.request.sendall(b"stream: OK\x00")


class _MockClamDServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        super().__init__((host, port), _MockClamDHandler)


@pytest.fixture
def mock_clamd():
    server = _MockClamDServer()
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    port = server.server_address[1]
    yield "127.0.0.1", port
    server.shutdown()
    server.server_close()


def test_eicar_scanner():
    assert eicar_scanner(CLEAN_PDF) is None
    assert eicar_scanner(b"prefix " + EICAR + b" suffix") == "EICAR-Test-File"


def test_clamav_unconfigured():
    s = get_settings()
    old_host = s.clamav_host
    try:
        s.clamav_host = ""
        assert clamav_scanner(CLEAN_PDF) is None
    finally:
        s.clamav_host = old_host


def test_clamav_clean_and_infected_streams(mock_clamd):
    host, port = mock_clamd
    s = get_settings()
    old_host, old_port = s.clamav_host, s.clamav_port
    try:
        s.clamav_host = host
        s.clamav_port = port

        # Clean file
        assert clamav_scanner(CLEAN_PDF) is None
        assert scan(CLEAN_PDF) is None

        # Infected file
        assert clamav_scanner(VIRUS_PAYLOAD) == "Win.Test.CustomVirus"
        assert scan(VIRUS_PAYLOAD) == "Win.Test.CustomVirus"
    finally:
        s.clamav_host = old_host
        s.clamav_port = old_port


def test_clamav_connection_error_fallback(caplog):
    s = get_settings()
    old_host, old_port = s.clamav_host, s.clamav_port
    try:
        s.clamav_host = "127.0.0.1"
        s.clamav_port = 65533  # closed port

        result = clamav_scanner(CLEAN_PDF)
        assert result is None  # Falls back gracefully
    finally:
        s.clamav_host = old_host
        s.clamav_port = old_port


async def test_document_upload_rejected_by_clamav(client, mock_clamd):
    host, port = mock_clamd
    s = get_settings()
    old_host, old_port = s.clamav_host, s.clamav_port

    from app.models import Patient

    pid = (await by_email(Patient, "patient1@example.com")).id
    h = await login_headers(client, "staff@hospital.example.com")

    try:
        s.clamav_host = host
        s.clamav_port = port

        # Upload containing virus trigger
        res = await client.post(
            f"/api/patients/{pid}/documents",
            headers=h,
            files={"file": ("infected.pdf", VIRUS_PAYLOAD, "application/pdf")},
            data={"doc_type": "lab_report"},
        )
        assert res.status_code == 422
        assert "File rejected by scanner: Win.Test.CustomVirus" in res.json()["detail"]
    finally:
        s.clamav_host = old_host
        s.clamav_port = old_port
