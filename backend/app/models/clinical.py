import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, uuid_pk

UUID_FK = UUID(as_uuid=True)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class Doctor(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "doctors"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("users.id", ondelete="RESTRICT"), unique=True
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    specialization: Mapped[str | None] = mapped_column(String(120))
    slot_minutes: Mapped[int] = mapped_column(Integer, default=30, server_default="30")


class Patient(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "patients"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_FK, ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    first_name: Mapped[str] = mapped_column(String(100), index=True)
    last_name: Mapped[str] = mapped_column(String(100), index=True)
    date_of_birth: Mapped[date] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(16))
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32))
    insurance_provider: Mapped[str | None] = mapped_column(String(200))
    insurance_id_encrypted: Mapped[str | None] = mapped_column(Text)
    allergies: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    blood_group: Mapped[str | None] = mapped_column(String(4))


class DoctorAvailability(Base):
    __tablename__ = "doctor_availability"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("doctors.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0=Monday
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class AvailabilityException(Base):
    __tablename__ = "availability_exceptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("doctors.id", ondelete="CASCADE"), index=True
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(200))


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("doctors.id", ondelete="RESTRICT"), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="booked")
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID_FK, ForeignKey("users.id", ondelete="SET NULL")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        # No two active appointments for one doctor may overlap.
        ExcludeConstraint(
            ("doctor_id", "="),
            (func.tstzrange(text("starts_at"), text("ends_at"), "[)"), "&&"),
            where=text("status IN ('booked','completed')"),
            using="gist",
            name="ex_appointments_no_overlap",
        ),
        Index(
            "uq_appointments_idempotency",
            "created_by",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class WaitlistEntry(Base, TimestampMixin):
    __tablename__ = "waitlist_entries"
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("doctors.id", ondelete="CASCADE"), index=True
    )
    desired_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="waiting")  # waiting|notified|fulfilled


class Visit(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "visits"
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("doctors.id", ondelete="RESTRICT"), index=True
    )
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_FK, ForeignKey("appointments.id", ondelete="SET NULL"), index=True
    )
    chief_complaint: Mapped[str | None] = mapped_column(Text)
    vitals: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    notes: Mapped[str | None] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(chief_complaint,'') || ' ' || "
            "coalesce(notes,'') || ' ' || coalesce(diagnosis,''))",
            persisted=True,
        ),
    )

    __table_args__ = (Index("ix_visits_search_vector", "search_vector", postgresql_using="gin"),)


class Prescription(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "prescriptions"
    id: Mapped[uuid.UUID] = uuid_pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("visits.id", ondelete="RESTRICT"), index=True
    )
    drug_name: Mapped[str] = mapped_column(String(200))
    dosage: Mapped[str | None] = mapped_column(String(100))
    frequency: Mapped[str | None] = mapped_column(String(100))
    duration: Mapped[str | None] = mapped_column(String(100))
    instructions: Mapped[str | None] = mapped_column(Text)


class Document(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_FK, ForeignKey("visits.id", ondelete="SET NULL")
    )
    doc_type: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID_FK, ForeignKey("users.id", ondelete="SET NULL")
    )


class RecordVersion(Base):
    """Immutable snapshot of a record before each edit (versioned edits)."""

    __tablename__ = "record_versions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID_FK)
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID_FK, ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "version", name="uq_record_versions_entity"),
    )


class AIConversation(Base, TimestampMixin):
    __tablename__ = "ai_conversations"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(24))  # triage | booking | faq
    state: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class AIMessage(Base):
    __tablename__ = "ai_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AISummary(Base, TimestampMixin):
    __tablename__ = "ai_summaries"
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID_FK, ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_FK, ForeignKey("visits.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(24))  # briefing | visit
    content: Mapped[dict] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID_FK, ForeignKey("users.id", ondelete="SET NULL")
    )


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_FK, ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(16))  # email | sms
    kind: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), default="sent")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID_FK, index=True)
    role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(16))  # read | create | update | delete | auth
    resource_type: Mapped[str] = mapped_column(String(40), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(300))
    status_code: Mapped[int] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
