import base64
import logging
import socketserver
import threading
from typing import Any
from urllib.error import URLError
import urllib.request
import json
import pytest

from app.core.config import get_settings
from app.services.email import send_email


class _MockSMTPHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.wfile.write(b"220 test-smtp ESMTP\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                break
            cmd = line.decode("utf-8", errors="ignore").strip()
            cmd_upper = cmd.upper()
            if cmd_upper.startswith("EHLO") or cmd_upper.startswith("HELO"):
                features = [b"250-test-smtp", b"250-AUTH PLAIN LOGIN", b"250-8BITMIME"]
                if getattr(self.server, "enable_starttls", False):
                    features.append(b"250-STARTTLS")
                features.append(b"250 HELP")
                self.wfile.write(b"\r\n".join(features) + b"\r\n")
            elif cmd_upper == "STARTTLS":
                self.server.starttls_called = True
                self.wfile.write(b"220 2.0.0 Ready to start TLS\r\n")
                # Stop here for test purposes if not performing full TLS handshake
                break
            elif cmd_upper.startswith("AUTH PLAIN"):
                parts = cmd.split(" ", 2)
                if len(parts) == 3:
                    raw = base64.b64decode(parts[2]).split(b"\x00")
                    if len(raw) >= 3:
                        self.server.auth_info = (raw[1].decode(), raw[2].decode())
                self.wfile.write(b"235 2.7.0 Authentication successful\r\n")
            elif cmd_upper.startswith("AUTH LOGIN"):
                self.wfile.write(b"334 VXNlcm5hbWU6\r\n")  # Username:
                user_line = self.rfile.readline().strip()
                username = base64.b64decode(user_line).decode()
                self.wfile.write(b"334 UGFzc3dvcmQ6\r\n")  # Password:
                pass_line = self.rfile.readline().strip()
                password = base64.b64decode(pass_line).decode()
                self.server.auth_info = (username, password)
                self.wfile.write(b"235 Authentication successful\r\n")
            elif cmd_upper.startswith("MAIL FROM:"):
                self.server.received_from.append(cmd)
                self.wfile.write(b"250 OK\r\n")
            elif cmd_upper.startswith("RCPT TO:"):
                self.server.received_to.append(cmd)
                self.wfile.write(b"250 OK\r\n")
            elif cmd_upper == "DATA":
                self.wfile.write(b"354 Start mail input; end with <CRLF>.<CRLF>\r\n")
                data = b""
                while True:
                    dline = self.rfile.readline()
                    if dline in (b".\r\n", b".\n"):
                        break
                    data += dline
                self.server.messages.append(data.decode("utf-8", errors="ignore"))
                self.wfile.write(b"250 OK: message queued\r\n")
            elif cmd_upper == "QUIT":
                self.wfile.write(b"221 Bye\r\n")
                break


class _MockSMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        super().__init__((host, port), _MockSMTPHandler)
        self.messages: list[str] = []
        self.received_from: list[str] = []
        self.received_to: list[str] = []
        self.auth_info: tuple[str, str] | None = None
        self.starttls_called: bool = False
        self.enable_starttls: bool = False


@pytest.fixture
def mock_smtp():
    server = _MockSMTPServer()
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = server.server_address[1]
    yield server, port
    server.shutdown()
    server.server_close()


def test_send_email_console(caplog):
    s = get_settings()
    old_backend = s.email_backend
    try:
        s.email_backend = "console"
        with caplog.at_level(logging.INFO, logger="app.email"):
            send_email("patient@example.com", "Test Subject", "Test Body")
        assert any(
            "email (console backend)" in record.message
            for record in caplog.records
        )
    finally:
        s.email_backend = old_backend


def test_send_email_smtp_no_host(caplog):
    s = get_settings()
    old_backend = s.email_backend
    old_host = s.smtp_host
    try:
        s.email_backend = "smtp"
        s.smtp_host = ""
        with caplog.at_level(logging.INFO, logger="app.email"):
            send_email("patient@example.com", "Test Subject", "Test Body")
        assert any(
            "email (console backend)" in record.message
            for record in caplog.records
        )
    finally:
        s.email_backend = old_backend
        s.smtp_host = old_host


def test_send_email_smtp_plain(mock_smtp):
    server, port = mock_smtp
    s = get_settings()
    old_backend, old_host, old_port, old_user, old_pass = (
        s.email_backend,
        s.smtp_host,
        s.smtp_port,
        s.smtp_user,
        s.smtp_password,
    )
    try:
        s.email_backend = "smtp"
        s.smtp_host = "127.0.0.1"
        s.smtp_port = port
        s.smtp_user = ""
        s.smtp_password = ""

        send_email("patient1@example.com", "Appointment Confirmation", "Your slot is booked.")

        assert len(server.messages) == 1
        msg_text = server.messages[0]
        assert "To: patient1@example.com" in msg_text
        assert "From: noreply@hospital" in msg_text
        assert "Subject: Appointment Confirmation" in msg_text
        assert "Your slot is booked." in msg_text
        assert any("patient1@example.com" in r for r in server.received_to)
    finally:
        s.email_backend = old_backend
        s.smtp_host = old_host
        s.smtp_port = old_port
        s.smtp_user = old_user
        s.smtp_password = old_pass


def test_send_email_smtp_with_auth(mock_smtp):
    server, port = mock_smtp
    s = get_settings()
    old_backend, old_host, old_port, old_user, old_pass = (
        s.email_backend,
        s.smtp_host,
        s.smtp_port,
        s.smtp_user,
        s.smtp_password,
    )
    try:
        s.email_backend = "smtp"
        s.smtp_host = "127.0.0.1"
        s.smtp_port = port
        s.smtp_user = "hospital_sender@hospital.example.com"
        s.smtp_password = "SecretPassword!123"

        send_email("doctor1@hospital.example.com", "Schedule Update", "New patients assigned.")

        assert len(server.messages) == 1
        msg_text = server.messages[0]
        assert "From: hospital_sender@hospital.example.com" in msg_text
        assert server.auth_info == ("hospital_sender@hospital.example.com", "SecretPassword!123")
    finally:
        s.email_backend = old_backend
        s.smtp_host = old_host
        s.smtp_port = old_port
        s.smtp_user = old_user
        s.smtp_password = old_pass


def test_send_email_smtp_starttls_detection(mock_smtp):
    server, port = mock_smtp
    server.enable_starttls = True
    s = get_settings()
    old_backend, old_host, old_port = s.email_backend, s.smtp_host, s.smtp_port
    try:
        s.email_backend = "smtp"
        s.smtp_host = "127.0.0.1"
        s.smtp_port = port
        s.smtp_user = ""
        s.smtp_password = ""

        # Calling send_email triggers starttls negotiation since server.enable_starttls is True
        try:
            send_email("user@example.com", "TLS Test", "Testing starttls call")
        except Exception:
            pass  # The mock server does not perform real SSL handshake; starttls_called is recorded
        assert server.starttls_called is True
    finally:
        s.email_backend = old_backend
        s.smtp_host = old_host
        s.smtp_port = old_port


def test_send_email_smtp_connection_failure():
    s = get_settings()
    old_backend, old_host, old_port = s.email_backend, s.smtp_host, s.smtp_port
    try:
        s.email_backend = "smtp"
        s.smtp_host = "127.0.0.1"
        s.smtp_port = 65534  # Closed port

        with pytest.raises(OSError):
            send_email("nobody@example.com", "Fail", "Should raise")
    finally:
        s.email_backend = old_backend
        s.smtp_host = old_host
        s.smtp_port = old_port


async def test_forgot_password_sends_smtp_email(client, mock_smtp):
    server, port = mock_smtp
    s = get_settings()
    old_backend, old_host, old_port = s.email_backend, s.smtp_host, s.smtp_port
    try:
        s.email_backend = "smtp"
        s.smtp_host = "127.0.0.1"
        s.smtp_port = port
        s.smtp_user = ""

        r = await client.post(
            "/api/auth/forgot-password",
            json={"email": "patient1@example.com"},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        assert len(server.messages) == 1
        msg = server.messages[0]
        assert "To: patient1@example.com" in msg
        assert "Subject: Password reset" in msg
        assert "Use this token to reset your password:" in msg
    finally:
        s.email_backend = old_backend
        s.smtp_host = old_host
        s.smtp_port = old_port


def test_mailpit_live_if_running():
    """If Mailpit is running (port 1025 for SMTP and 8025 for HTTP API), test real delivery."""
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8025/api/v1/messages", timeout=1)
        data = json.loads(req.read().decode())
    except (URLError, OSError):
        pytest.skip("Mailpit is not running on localhost:8025/1025; skipping live test")

    s = get_settings()
    old_backend, old_host, old_port = s.email_backend, s.smtp_host, s.smtp_port
    try:
        s.email_backend = "smtp"
        s.smtp_host = "127.0.0.1"
        s.smtp_port = 1025
        s.smtp_user = ""
        s.smtp_password = ""

        unique_subject = f"Mailpit Test {base64.b64encode(b'hospital-live').decode()}"
        send_email("patient@example.com", unique_subject, "Live Mailpit message body")

        # Verify via Mailpit REST API
        req2 = urllib.request.urlopen("http://127.0.0.1:8025/api/v1/messages", timeout=2)
        messages = json.loads(req2.read().decode()).get("messages", [])
        subjects = [m.get("Subject") for m in messages]
        assert unique_subject in subjects
    finally:
        s.email_backend = old_backend
        s.smtp_host = old_host
        s.smtp_port = old_port
