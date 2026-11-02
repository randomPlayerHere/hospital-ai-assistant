from cryptography.fernet import Fernet
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Patient
from app.scripts.rotate_encryption_key import rotate_keys
from tests.conftest import ADMIN, login_headers


async def test_field_encryption_key_rotation(client):
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()

    fernet1 = Fernet(key1.encode())
    fernet2 = Fernet(key2.encode())

    # Seed/update a patient with key1
    raw_insurance = "INS-TEST-998877"
    ciphertext1 = fernet1.encrypt(raw_insurance.encode()).decode()

    async with SessionLocal() as db:
        patient = (
            await db.execute(select(Patient).limit(1))
        ).scalar_one()
        patient.insurance_id_encrypted = ciphertext1
        await db.commit()
        patient_id = patient.id

    # Run key rotation
    rotated = await rotate_keys(key1, key2)
    assert rotated >= 1

    # Verify patient record now decryptable with key2
    async with SessionLocal() as db:
        p_after = (
            await db.execute(select(Patient).where(Patient.id == patient_id))
        ).scalar_one()
        assert p_after.insurance_id_encrypted != ciphertext1

        # key2 successfully decrypts to original plaintext
        decrypted = fernet2.decrypt(p_after.insurance_id_encrypted.encode()).decode()
        assert decrypted == raw_insurance

        # key1 fails to decrypt
        with pytest.raises(Exception):
            fernet1.decrypt(p_after.insurance_id_encrypted.encode())


async def test_key_rotation_invalid_args():
    key = Fernet.generate_key().decode()
    with pytest.raises(ValueError):
        await rotate_keys("", key)
    with pytest.raises(ValueError):
        await rotate_keys(key, key)
