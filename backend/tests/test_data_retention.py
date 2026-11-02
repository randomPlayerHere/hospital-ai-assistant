import uuid
from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Document, Patient, User
from app.scripts.purge_data import purge_expired_tokens, purge_patient, purge_soft_deleted_patients
from tests.conftest import ADMIN, login_headers
from tests.helpers import by_email


async def test_purge_active_patient_rejected():
    async with SessionLocal() as db:
        patient = (await db.execute(select(Patient).where(Patient.deleted_at.is_(None)))).scalars().first()
        assert patient is not None
        with pytest.raises(ValueError, match="active"):
            await purge_patient(db, patient.id)


async def test_purge_soft_deleted_patient_dry_run_and_actual(client):
    from app.services.storage import get_storage

    h = await login_headers(client, ADMIN[0], ADMIN[1])

    # Find a patient and mark for deletion via deletion-request endpoint
    patient = await by_email(Patient, "patient1@example.com")
    assert patient.deleted_at is None

    res = await client.post(f"/api/admin/patients/{patient.id}/deletion-request", headers=h)
    assert res.status_code == 202

    async with SessionLocal() as db:
        # Dry-run: records remain
        dry_counts = await purge_patient(db, patient.id, dry_run=True)
        assert isinstance(dry_counts, dict)

        pat_check = (await db.execute(select(Patient).where(Patient.id == patient.id))).scalar_one_or_none()
        assert pat_check is not None

        # Actual purge
        actual_counts = await purge_patient(db, patient.id, dry_run=False)
        assert "user_account" in actual_counts

        # Verify completely deleted from database
        pat_purged = (await db.execute(select(Patient).where(Patient.id == patient.id))).scalar_one_or_none()
        assert pat_purged is None

        user_purged = (await db.execute(select(User).where(User.id == patient.user_id))).scalar_one_or_none()
        assert user_purged is None


async def test_purge_expired_tokens():
    counts = await purge_expired_tokens(dry_run=False)
    assert isinstance(counts, dict)
    assert "expired_password_resets" in counts
    assert "expired_refresh_tokens" in counts
