"""Field encryption key rotation script.

Usage:
  python -m app.scripts.rotate_encryption_key --old-key <key> --new-key <key>
"""

import argparse
import asyncio
import sys

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Patient


async def rotate_keys(old_key: str, new_key: str) -> int:
    """Re-encrypt all Patient insurance_id fields from old_key to new_key."""
    if not old_key or not new_key:
        raise ValueError("Both old_key and new_key must be provided")
    if old_key == new_key:
        raise ValueError("Old key and new key cannot be identical")

    fernet_old = Fernet(old_key.encode() if isinstance(old_key, str) else old_key)
    fernet_new = Fernet(new_key.encode() if isinstance(new_key, str) else new_key)

    async with SessionLocal() as db:
        patients = (
            await db.execute(
                select(Patient).where(Patient.insurance_id_encrypted.isnot(None))
            )
        ).scalars().all()

        rotated_count = 0
        for p in patients:
            if not p.insurance_id_encrypted:
                continue
            try:
                # Decrypt with old key
                plaintext = fernet_old.decrypt(p.insurance_id_encrypted.encode()).decode()
            except Exception as exc:
                await db.rollback()
                raise RuntimeError(
                    f"Failed to decrypt record for patient {p.id} with old key: {exc}"
                ) from exc

            # Re-encrypt with new key
            new_ciphertext = fernet_new.encrypt(plaintext.encode()).decode()

            # Pre-flight check: ensure new ciphertext is decryptable
            verification = fernet_new.decrypt(new_ciphertext.encode()).decode()
            if verification != plaintext:
                await db.rollback()
                raise RuntimeError(f"Integrity check failed for patient {p.id}")

            p.insurance_id_encrypted = new_ciphertext
            rotated_count += 1

        await db.commit()
        return rotated_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate patient field encryption keys")
    parser.add_argument(
        "--old-key",
        default="",
        help="Current Fernet key (defaults to FIELD_ENCRYPTION_KEY from environment)",
    )
    parser.add_argument(
        "--new-key",
        required=True,
        help="New Fernet key to re-encrypt records with",
    )
    args = parser.parse_args()

    old_key = args.old_key or get_settings().field_encryption_key
    if not old_key:
        print("Error: --old-key not specified and FIELD_ENCRYPTION_KEY not set", file=sys.stderr)
        sys.exit(1)

    try:
        count = asyncio.run(rotate_keys(old_key, args.new_key))
        print(f"Successfully rotated encryption keys for {count} patient records.")
    except Exception as exc:
        print(f"Key rotation failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
