import uuid
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.models import (
    Appointment,
    AvailabilityException,
    Department,
    Doctor,
    DoctorAvailability,
    Patient,
    User,
    WaitlistEntry,
)
from app.schemas.scheduling import (
    AppointmentOut,
    AvailabilityIn,
    AvailabilityOut,
    BookIn,
    DepartmentOut,
    DoctorOut,
    ExceptionIn,
    ExceptionOut,
    RescheduleIn,
    SlotConfigIn,
    SlotOut,
    WaitlistIn,
    WaitlistOut,
)
from app.services import scheduling as svc
from app.services.access import authorize_patient_access, get_doctor_for_user, get_patient_for_user

router = APIRouter(prefix="/api", tags=["scheduling"])


async def _doctor_out(db: AsyncSession, d: Doctor) -> DoctorOut:
    user = await db.get(User, d.user_id)
    dept = await db.get(Department, d.department_id)
    return DoctorOut(
        id=d.id,
        name=user.full_name if user else "",
        department_id=d.department_id,
        department=dept.name if dept else "",
        specialization=d.specialization,
        slot_minutes=d.slot_minutes,
    )


async def _get_doctor(db: AsyncSession, doctor_id: uuid.UUID) -> Doctor:
    doctor = (
        await db.execute(select(Doctor).where(Doctor.id == doctor_id, Doctor.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if doctor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found")
    return doctor


# ---- directory & availability -------------------------------------------------


@router.get("/departments", response_model=list[DepartmentOut])
async def departments(
    db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
) -> list[Department]:
    return list((await db.execute(select(Department).order_by(Department.name))).scalars())


@router.get("/doctors", response_model=list[DoctorOut])
async def doctors(
    department_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DoctorOut]:
    stmt = (
        select(Doctor, User.full_name, Department.name)
        .join(User, User.id == Doctor.user_id)
        .join(Department, Department.id == Doctor.department_id)
        .where(Doctor.deleted_at.is_(None))
        .order_by(User.full_name)
    )
    if department_id:
        stmt = stmt.where(Doctor.department_id == department_id)
    return [
        DoctorOut(
            id=d.id,
            name=name,
            department_id=d.department_id,
            department=dept,
            specialization=d.specialization,
            slot_minutes=d.slot_minutes,
        )
        for d, name, dept in (await db.execute(stmt)).all()
    ]


@router.get("/doctors/me", response_model=DoctorOut)
async def my_doctor_profile(
    db: AsyncSession = Depends(get_db), user: User = Depends(require_roles("doctor"))
) -> DoctorOut:
    doctor = await get_doctor_for_user(db, user)
    if doctor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor profile not found")
    return await _doctor_out(db, doctor)


@router.get("/doctors/{doctor_id}/slots", response_model=list[SlotOut])
async def slots(
    doctor_id: uuid.UUID,
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[SlotOut]:
    if date_to < date_from or (date_to - date_from).days > svc.MAX_RANGE_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid date range (max 31 days)"
        )
    doctor = await _get_doctor(db, doctor_id)
    return [
        SlotOut(starts_at=s, ends_at=e)
        for s, e in await svc.free_slots(db, doctor, date_from, date_to)
    ]


async def _manage_doctor(db: AsyncSession, user: User, doctor_id: uuid.UUID) -> Doctor:
    doctor = await _get_doctor(db, doctor_id)
    if user.role.name == "doctor":
        own = await get_doctor_for_user(db, user)
        if own is None or own.id != doctor.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Cannot manage another doctor's schedule"
            )
    return doctor


@router.get("/doctors/{doctor_id}/availability", response_model=list[AvailabilityOut])
async def get_availability(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DoctorAvailability]:
    await _get_doctor(db, doctor_id)
    rows = await db.execute(
        select(DoctorAvailability)
        .where(DoctorAvailability.doctor_id == doctor_id)
        .order_by(DoctorAvailability.weekday, DoctorAvailability.start_time)
    )
    return list(rows.scalars())


@router.put("/doctors/{doctor_id}/availability", response_model=list[AvailabilityOut])
async def set_availability(
    doctor_id: uuid.UUID,
    body: list[AvailabilityIn],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "doctor")),
) -> list[DoctorAvailability]:
    await _manage_doctor(db, user, doctor_id)
    by_day: dict[int, list[AvailabilityIn]] = {}
    for a in body:
        by_day.setdefault(a.weekday, []).append(a)
    for items in by_day.values():
        items.sort(key=lambda a: a.start_time)
        for prev, cur in pairwise(items):
            if cur.start_time < prev.end_time:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Overlapping windows")
    old = await db.execute(
        select(DoctorAvailability).where(DoctorAvailability.doctor_id == doctor_id)
    )
    for row in old.scalars():
        await db.delete(row)
    new = [DoctorAvailability(doctor_id=doctor_id, **a.model_dump()) for a in body]
    db.add_all(new)
    await db.commit()
    return new


@router.put("/doctors/{doctor_id}/slot-config", response_model=DoctorOut)
async def set_slot_config(
    doctor_id: uuid.UUID,
    body: SlotConfigIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "doctor")),
) -> DoctorOut:
    if user.role.name == "doctor":
        me = await get_doctor_for_user(db, user)
        if me is None or me.id != doctor_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "May only configure your own slots")
    doctor = await _get_doctor(db, doctor_id)
    doctor.slot_minutes = body.slot_minutes
    await db.commit()
    return await _doctor_out(db, doctor)


@router.get("/doctors/{doctor_id}/exceptions", response_model=list[ExceptionOut])
async def list_exceptions(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "doctor", "staff")),
) -> list[AvailabilityException]:
    await _get_doctor(db, doctor_id)
    rows = await db.execute(
        select(AvailabilityException)
        .where(AvailabilityException.doctor_id == doctor_id)
        .order_by(AvailabilityException.start_date)
    )
    return list(rows.scalars())


@router.post(
    "/doctors/{doctor_id}/exceptions",
    response_model=ExceptionOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_exception(
    doctor_id: uuid.UUID,
    body: ExceptionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "doctor")),
) -> AvailabilityException:
    await _manage_doctor(db, user, doctor_id)
    exc = AvailabilityException(doctor_id=doctor_id, **body.model_dump())
    db.add(exc)
    await db.commit()
    await db.refresh(exc)
    return exc


@router.delete("/doctors/{doctor_id}/exceptions/{exc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exception(
    doctor_id: uuid.UUID,
    exc_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "doctor")),
) -> Response:
    await _manage_doctor(db, user, doctor_id)
    exc = await db.get(AvailabilityException, exc_id)
    if exc is None or exc.doctor_id != doctor_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exception not found")
    await db.delete(exc)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- appointments -------------------------------------------------------------


async def _resolve_patient_id(
    db: AsyncSession, user: User, requested: uuid.UUID | None
) -> uuid.UUID:
    if user.role.name == "patient":
        patient = await get_patient_for_user(db, user)
        if patient is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient profile not found")
        return patient.id
    if requested is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "patient_id is required")
    return (await authorize_patient_access(db, user, requested)).id


@router.post("/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def book_appointment(
    body: BookIn,
    response: Response,
    idempotency_key: str | None = Header(default=None, max_length=128),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("patient", "staff", "admin")),
) -> Appointment:
    patient_id = await _resolve_patient_id(db, user, body.patient_id)
    appt, created = await svc.book(
        db,
        patient_id=patient_id,
        doctor_id=body.doctor_id,
        starts_at=body.starts_at,
        reason=body.reason,
        created_by=user.id,
        idempotency_key=idempotency_key,
    )
    if not created:
        response.status_code = status.HTTP_200_OK  # replay of an earlier successful request
    return appt


@router.get("/appointments", response_model=list[AppointmentOut])
async def list_appointments(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    doctor_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AppointmentOut]:
    stmt = select(Appointment).order_by(Appointment.starts_at)
    role = user.role.name
    if role == "patient":
        patient = await get_patient_for_user(db, user)
        stmt = stmt.where(Appointment.patient_id == (patient.id if patient else None))
    elif role == "doctor":
        doctor = await get_doctor_for_user(db, user)
        stmt = stmt.where(Appointment.doctor_id == (doctor.id if doctor else None))
    if doctor_id and role != "doctor":
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    if patient_id and role in ("staff", "admin", "doctor"):
        stmt = stmt.where(Appointment.patient_id == patient_id)
    if status_filter:
        stmt = stmt.where(Appointment.status == status_filter)
    tz = svc.hospital_tz()
    if date_from:
        stmt = stmt.where(
            Appointment.starts_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=tz)
        )
    if date_to:
        stmt = stmt.where(
            Appointment.starts_at
            < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        )
    appts = list((await db.execute(stmt.limit(500))).scalars())
    return await _with_names(db, appts)


async def _with_names(db: AsyncSession, appts: list[Appointment]) -> list[AppointmentOut]:
    """Attach display names (patients for staff/doctors, doctors for everyone)."""
    pids = {a.patient_id for a in appts}
    dids = {a.doctor_id for a in appts}
    patients: dict[uuid.UUID, str] = {}
    doctors_: dict[uuid.UUID, str] = {}
    if pids:
        rows = await db.execute(select(Patient).where(Patient.id.in_(pids)))
        patients = {p.id: f"{p.first_name} {p.last_name}" for p in rows.scalars()}
    if dids:
        name_rows = await db.execute(
            select(Doctor.id, User.full_name)
            .join(User, User.id == Doctor.user_id)
            .where(Doctor.id.in_(dids))
        )
        for row in name_rows.all():
            doctors_[row[0]] = row[1]
    out = []
    for a in appts:
        o = AppointmentOut.model_validate(a)
        o.patient_name, o.doctor_name = patients.get(a.patient_id), doctors_.get(a.doctor_id)
        out.append(o)
    return out


async def _authorized_appt(
    db: AsyncSession, user: User, appt_id: uuid.UUID, roles: tuple[str, ...]
) -> Appointment:
    appt = await db.get(Appointment, appt_id)
    role = user.role.name
    ok = appt is not None and role in roles
    if ok and appt is not None and role == "patient":
        patient = await get_patient_for_user(db, user)
        ok = patient is not None and patient.id == appt.patient_id
    if ok and appt is not None and role == "doctor":
        doctor = await get_doctor_for_user(db, user)
        ok = doctor is not None and doctor.id == appt.doctor_id
    if not ok or appt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    return appt


@router.post("/appointments/{appt_id}/reschedule", response_model=AppointmentOut)
async def reschedule_appointment(
    appt_id: uuid.UUID,
    body: RescheduleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("patient", "staff", "admin")),
) -> Appointment:
    appt = await _authorized_appt(db, user, appt_id, ("patient", "staff", "admin"))
    return await svc.reschedule(db, appt, body.starts_at)


@router.post("/appointments/{appt_id}/cancel", response_model=AppointmentOut)
async def cancel_appointment(
    appt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("patient", "staff", "admin", "doctor")),
) -> Appointment:
    appt = await _authorized_appt(db, user, appt_id, ("patient", "staff", "admin", "doctor"))
    return await svc.cancel(db, appt)


@router.post("/appointments/{appt_id}/complete", response_model=AppointmentOut)
async def complete_appointment(
    appt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("doctor")),
) -> Appointment:
    appt = await _authorized_appt(db, user, appt_id, ("doctor",))
    return await svc.set_outcome(db, appt, "completed")


@router.post("/appointments/{appt_id}/no-show", response_model=AppointmentOut)
async def no_show_appointment(
    appt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("doctor", "staff", "admin")),
) -> Appointment:
    appt = await _authorized_appt(db, user, appt_id, ("doctor", "staff", "admin"))
    return await svc.set_outcome(db, appt, "no_show")


# ---- waitlist -----------------------------------------------------------------


@router.post("/waitlist", response_model=WaitlistOut, status_code=status.HTTP_201_CREATED)
async def join_waitlist(
    body: WaitlistIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("patient", "staff", "admin")),
) -> WaitlistEntry:
    patient_id = await _resolve_patient_id(db, user, body.patient_id)
    await _get_doctor(db, body.doctor_id)
    if body.desired_date < datetime.now(UTC).date():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Date is in the past")
    dup = (
        await db.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.patient_id == patient_id,
                WaitlistEntry.doctor_id == body.doctor_id,
                WaitlistEntry.desired_date == body.desired_date,
                WaitlistEntry.status == "waiting",
            )
        )
    ).scalar_one_or_none()
    if dup:
        return dup
    entry = WaitlistEntry(
        patient_id=patient_id, doctor_id=body.doctor_id, desired_date=body.desired_date
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.get("/waitlist", response_model=list[WaitlistOut])
async def list_waitlist(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("patient", "staff", "admin")),
) -> list[WaitlistEntry]:
    stmt = select(WaitlistEntry).order_by(WaitlistEntry.created_at)
    if user.role.name == "patient":
        patient = await get_patient_for_user(db, user)
        stmt = stmt.where(WaitlistEntry.patient_id == (patient.id if patient else None))
    return list((await db.execute(stmt.limit(500))).scalars())


@router.delete("/waitlist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def leave_waitlist(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("patient", "staff", "admin")),
) -> Response:
    entry = await db.get(WaitlistEntry, entry_id)
    if entry is not None and user.role.name == "patient":
        patient = await get_patient_for_user(db, user)
        if patient is None or patient.id != entry.patient_id:
            entry = None
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Waitlist entry not found")
    await db.delete(entry)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
