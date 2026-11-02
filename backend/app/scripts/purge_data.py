"""Permanent data deletion and retention policy execution script.

Usage:
  python -m app.scripts.purge_data --dry-run
  python -m app.scripts.purge_data --patient-id <uuid>
  python -m app.scripts.purge_data --purge-soft-deleted-older-than-days 30
  python -m app.scripts.purge_data --purge-expired-tokens
"""

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.models import (
    AIConversation,
    AIMessage,
    AISummary,
    Appointment,
    Document,
    Notification,
    PasswordResetToken,
    Patient,
    Prescription,
    RecordVersion,
    RefreshToken,
    User,
    Visit,
    WaitlistEntry,
)
from app.services.storage import get_storage

log = logging.getLogger("app.retention")


async def purge_patient(db, patient_id: uuid.UUID, dry_run: bool = False) -> dict[str, int]:
    """Permanently delete a soft-deleted patient and all associated clinical & account records."""
    patient = (
        await db.execute(select(Patient).where(Patient.id == patient_id))
    ).scalar_one_or_none()

    if patient is None:
        raise ValueError(f"Patient {patient_id} not found")
    if patient.deleted_at is None:
        raise ValueError(f"Patient {patient_id} is active (not soft-deleted); cannot purge")

    counts = {}

    # 1. Documents & physical storage files
    docs = (
        await db.execute(select(Document).where(Document.patient_id == patient_id))
    ).scalars().all()
    counts["documents"] = len(docs)

    if not dry_run:
        storage = get_storage()
        for doc in docs:
            try:
                await storage.delete(doc.storage_key)
            except Exception as exc:
                log.warning("Failed to delete storage file %s: %s", doc.storage_key, exc)

    # 2. Visits, prescriptions, versions
    visits = (
        await db.execute(select(Visit).where(Visit.patient_id == patient_id))
    ).scalars().all()
    visit_ids = [v.id for v in visits]
    counts["visits"] = len(visit_ids)

    # 3. Appointments & waitlist
    appts = (
        await db.execute(select(Appointment).where(Appointment.patient_id == patient_id))
    ).scalars().all()
    appt_ids = [a.id for a in appts]
    counts["appointments"] = len(appt_ids)

    # 4. AI conversations
    convs = (
        await db.execute(select(AIConversation).where(AIConversation.patient_id == patient_id))
    ).scalars().all()
    conv_ids = [c.id for c in convs]
    counts["ai_conversations"] = len(conv_ids)

    user_id = patient.user_id

    if dry_run:
        return counts

    # Execute cascaded deletes
    if visit_ids:
        await db.execute(delete(Prescription).where(Prescription.visit_id.in_(visit_ids)))
        await db.execute(
            delete(RecordVersion).where(
                RecordVersion.record_type == "visit", RecordVersion.record_id.in_(visit_ids)
            )
        )
        await db.execute(delete(Visit).where(Visit.id.in_(visit_ids)))

    if appt_ids:
        await db.execute(delete(Notification).where(Notification.appointment_id.in_(appt_ids)))
        await db.execute(delete(Appointment).where(Appointment.id.in_(appt_ids)))

    await db.execute(delete(WaitlistEntry).where(WaitlistEntry.patient_id == patient_id))
    await db.execute(delete(Document).where(Document.patient_id == patient_id))

    if conv_ids:
        await db.execute(delete(AIMessage).where(AIMessage.conversation_id.in_(conv_ids)))
        await db.execute(delete(AISummary).where(AISummary.conversation_id.in_(conv_ids)))
        await db.execute(delete(AIConversation).where(AIConversation.id.in_(conv_ids)))

    await db.execute(delete(Patient).where(Patient.id == patient_id))

    if user_id:
        await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
        await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
        counts["user_account"] = 1

    await db.commit()
    return counts


async def purge_soft_deleted_patients(days: int, dry_run: bool = False) -> int:
    """Purge all patients soft-deleted more than `days` ago."""
    threshold = datetime.now(UTC) - timedelta(days=days)
    async with SessionLocal() as db:
        stale_patients = (
            await db.execute(
                select(Patient.id).where(Patient.deleted_at.isnot(None), Patient.deleted_at <= threshold)
            )
        ).scalars().all()

        purged = 0
        for pid in stale_patients:
            await purge_patient(db, pid, dry_run=dry_run)
            purged += 1
        return purged


async def purge_expired_tokens(dry_run: bool = False) -> dict[str, int]:
    """Purge expired password reset tokens and revoked refresh tokens older than 30 days."""
    now = datetime.now(UTC)
    revoked_threshold = now - timedelta(days=30)
    counts = {}

    async with SessionLocal() as db:
        if dry_run:
            resets = (
                await db.execute(
                    select(PasswordResetToken).where(
                        (PasswordResetToken.expires_at < now) | (PasswordResetToken.used_at.isnot(None))
                    )
                )
            ).scalars().all()
            refreshes = (
                await db.execute(
                    select(RefreshToken).where(
                        (RefreshToken.expires_at < now)
                        | ((RefreshToken.revoked_at.isnot(None)) & (RefreshToken.revoked_at < revoked_threshold))
                    )
                )
            ).scalars().all()
            return {"expired_password_resets": len(resets), "expired_refresh_tokens": len(refreshes)}

        del_resets = await db.execute(
            delete(PasswordResetToken).where(
                (PasswordResetToken.expires_at < now) | (PasswordResetToken.used_at.isnot(None))
            )
        )
        del_refreshes = await db.execute(
            delete(RefreshToken).where(
                (RefreshToken.expires_at < now)
                | ((RefreshToken.revoked_at.isnot(None)) & (RefreshToken.revoked_at < revoked_threshold))
            )
        )
        await db.commit()
        counts["expired_password_resets"] = del_resets.rowcount
        counts["expired_refresh_tokens"] = del_refreshes.rowcount
        return counts


async def run_cli(args) -> None:
    if args.patient_id:
        async with SessionLocal() as db:
            counts = await purge_patient(db, uuid.UUID(args.patient_id), dry_run=args.dry_run)
            action = "Would purge" if args.dry_run else "Successfully purged"
            print(f"{action} patient {args.patient_id}: {counts}")

    if args.purge_soft_deleted_older_than_days is not None:
        count = await purge_soft_deleted_patients(args.purge_soft_deleted_older_than_days, dry_run=args.dry_run)
        action = "Would purge" if args.dry_run else "Successfully purged"
        print(f"{action} {count} patients soft-deleted > {args.purge_soft_deleted_older_than_days} days ago.")

    if args.purge_expired_tokens:
        counts = await purge_expired_tokens(dry_run=args.dry_run)
        action = "Would purge" if args.dry_run else "Successfully purged"
        print(f"{action} tokens: {counts}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge soft-deleted patient data and expired credentials")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be purged without deleting")
    parser.add_argument("--patient-id", help="UUID of specific soft-deleted patient to permanently purge")
    parser.add_argument(
        "--purge-soft-deleted-older-than-days",
        type=int,
        metavar="DAYS",
        help="Purge patients soft-deleted more than DAYS ago (e.g. 30)",
    )
    parser.add_argument(
        "--purge-expired-tokens",
        action="store_true",
        help="Purge expired password reset tokens and stale revoked refresh tokens",
    )
    args = parser.parse_args()

    if not (args.patient_id or args.purge_soft_deleted_older_than_days is not None or args.purge_expired_tokens):
        parser.print_help()
        sys.exit(1)

    asyncio.run(run_cli(args))


if __name__ == "__main__":
    main()
