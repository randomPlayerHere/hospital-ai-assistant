import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse


def generate_totp_secret() -> str:
    """Generate a 160-bit (20-byte) base32 secret string without padding."""
    return base64.b32encode(secrets.token_bytes(20)).decode("utf-8").rstrip("=")


def get_totp_uri(secret: str, email: str, issuer: str = "Hospital AI") -> str:
    """Return standard otpauth:// URI for authenticator apps (Google Authenticator, etc.)."""
    label = f"{issuer}:{email}"
    params = urllib.parse.urlencode(
        {"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": 6, "period": 30}
    )
    return f"otpauth://totp/{urllib.parse.quote(label)}?{params}"


def get_totp_code(secret: str, intervals_no: int | None = None) -> str:
    """Calculate the 6-digit RFC 6238 TOTP code for a time window."""
    if intervals_no is None:
        intervals_no = int(time.time()) // 30
    pad = (8 - len(secret) % 8) % 8
    key = base64.b32decode(secret + "=" * pad, casefold=True)
    msg = struct.pack(">Q", intervals_no)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = (struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000
    return str(code).zfill(6)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    """Verify code against current timestamp ± window intervals (default ±30s)."""
    clean_code = code.strip().replace(" ", "")
    if len(clean_code) != 6 or not clean_code.isdigit():
        return False
    current = int(time.time()) // 30
    for step in range(-window, window + 1):
        if hmac.compare_digest(get_totp_code(secret, current + step), clean_code):
            return True
    return False
