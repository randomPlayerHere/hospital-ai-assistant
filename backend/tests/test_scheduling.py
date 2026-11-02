import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.jobs.reminders import reminder_kind, send_due_reminders
from app.models import Appointment, Doctor, Notification, Patient, WaitlistEntry
from tests.conftest import ADMIN, login_headers
from tests.helpers import by_email

D1, D2, S, P1, P2, P3 = (
    "doctor1@hospital.example.com", "doctor2@hospital.example.com", "staff@hospital.example.com",
    "patient1@example.com", "patient2@example.com", "patient3@example.com",
)  # fmt: skip


def today() -> date:
    return datetime.now(UTC).date()


async def doctor_id(email=D1) -> str:
    return str((await by_email(Doctor, email)).id)


async def open_slots(client, h, did, days=14):
    start_day = today()
    r = await client.get(
        f"/api/doctors/{did}/slots",
        params={
            "from": start_day.isoformat(),
            "to": (start_day + timedelta(days=days)).isoformat(),
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def first_slot(client, h, did):
    return (await open_slots(client, h, did))[0]["starts_at"]


async def book(client, h, did, start, patient_id=None, key=None):
    body = {"doctor_id": did, "starts_at": start, "reason": "checkup"}
    if patient_id:
        body["patient_id"] = str(patient_id)
    return await client.post(
        "/api/appointments", json=body, headers={**h, **({"Idempotency-Key": key} if key else {})}
    )


async def test_slot_generation_respects_template_and_exceptions(client):
    h, did = await login_headers(client, P1), await doctor_id()
    slots = await open_slots(client, h, did)
    assert slots and all(
        datetime.fromisoformat(s["ends_at"]) - datetime.fromisoformat(s["starts_at"])
        == timedelta(minutes=30)
        for s in slots
    )
    day = datetime.fromisoformat(slots[0]["starts_at"]).astimezone().date()
    hd = await login_headers(client, D1)
    # doctor blocks a day off (leave)
    r = await client.post(
        f"/api/doctors/{did}/exceptions",
        headers=hd,
        json={
            "start_date": str(day - timedelta(days=1)),
            "end_date": str(day + timedelta(days=1)),
            "reason": "leave",
        },
    )
    assert r.status_code == 201
    exc_id = r.json()["id"]
    new_slots = await open_slots(client, h, did)
    assert all(s["starts_at"] != slots[0]["starts_at"] for s in new_slots)
    assert (
        await client.delete(f"/api/doctors/{did}/exceptions/{exc_id}", headers=hd)
    ).status_code == 204
    assert (await open_slots(client, h, did))[0]["starts_at"] == slots[0]["starts_at"]


async def test_booking_removes_slot_and_slot_config_change(client):
    hp, did = await login_headers(client, P1), await doctor_id()
    start = await first_slot(client, hp, did)
    r = await book(client, hp, did, start)
    assert r.status_code == 201 and r.json()["status"] == "booked"
    assert start not in [s["starts_at"] for s in await open_slots(client, hp, did)]
    ha = await login_headers(client, ADMIN[0], ADMIN[1])
    assert (
        await client.put(f"/api/doctors/{did}/slot-config", json={"slot_minutes": 15}, headers=ha)
    ).status_code == 200
    s = await open_slots(client, hp, did)
    assert datetime.fromisoformat(s[1]["starts_at"]) - datetime.fromisoformat(
        s[0]["starts_at"]
    ) in (timedelta(minutes=15), timedelta(days=1) - timedelta(hours=7, minutes=45))
    # Doctor can configure their own slot length
    hd = await login_headers(client, "doctor1@hospital.example.com")
    d_me = (await client.get("/api/doctors/me", headers=hd)).json()
    assert (
        await client.put(f"/api/doctors/{d_me['id']}/slot-config", json={"slot_minutes": 20}, headers=hd)
    ).status_code == 200
    await client.put(f"/api/doctors/{d_me['id']}/slot-config", json={"slot_minutes": 30}, headers=hd)
    await client.put(f"/api/doctors/{did}/slot-config", json={"slot_minutes": 30}, headers=ha)


async def test_cannot_book_taken_or_invalid_slots(client):
    hp1, hp2, did = (
        await login_headers(client, P1),
        await login_headers(client, P2),
        await doctor_id(),
    )
    start = await first_slot(client, hp1, did)
    assert (await book(client, hp1, did, start)).status_code == 201
    assert (await book(client, hp2, did, start)).status_code == 409
    off_grid = (datetime.fromisoformat(start) + timedelta(minutes=7)).isoformat()
    assert (await book(client, hp2, did, off_grid)).status_code == 409
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert (await book(client, hp2, did, past)).status_code == 422
    far = (datetime.now(UTC) + timedelta(days=400)).isoformat()
    assert (await book(client, hp2, did, far)).status_code == 422
    assert (
        await client.post(
            "/api/appointments",
            headers=hp2,
            json={"doctor_id": did, "starts_at": "2030-01-01T10:00:00"},
        )
    ).status_code == 422  # naive datetime
    assert (await book(client, hp2, str(uuid.uuid4()), start)).status_code == 404


async def test_idempotency_key_returns_same_booking(client):
    hp, did = await login_headers(client, P1), await doctor_id()
    start = await first_slot(client, hp, did)
    r1 = await book(client, hp, did, start, key="abc-123")
    r2 = await book(client, hp, did, start, key="abc-123")
    assert r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"]
    async with SessionLocal() as db:
        assert (await db.execute(select(func.count()).select_from(Appointment))).scalar_one() == 1


async def test_staff_books_for_patient_and_patient_id_rules(client):
    hs, did = await login_headers(client, S), await doctor_id()
    pid = (await by_email(Patient, P1)).id
    start = await first_slot(client, hs, did)
    assert (await book(client, hs, did, start)).status_code == 422  # patient_id required
    r = await book(client, hs, did, start, patient_id=pid)
    assert r.status_code == 201 and r.json()["patient_id"] == str(pid)
    # a patient's supplied patient_id is ignored: they can only book for themselves
    hp2 = await login_headers(client, P2)
    other = (await open_slots(client, hp2, did))[1]["starts_at"]
    r = await book(client, hp2, did, other, patient_id=pid)
    assert r.json()["patient_id"] == str((await by_email(Patient, P2)).id)


async def test_role_permissions_on_booking(client):
    did = await doctor_id()
    hd = await login_headers(client, D1)
    assert (await book(client, hd, did, "2030-01-01T10:00:00+00:00")).status_code == 403
    assert (await client.post("/api/appointments", json={})).status_code == 401


async def test_reschedule_and_cancel_permissions(client):
    hp1, hp2, hs, did = (
        await login_headers(client, P1),
        await login_headers(client, P2),
        await login_headers(client, S),
        await doctor_id(),
    )
    slots = await open_slots(client, hp1, did)
    appt = (await book(client, hp1, did, slots[0]["starts_at"])).json()
    assert (
        await client.post(f"/api/appointments/{appt['id']}/cancel", headers=hp2)
    ).status_code == 404
    r = await client.post(
        f"/api/appointments/{appt['id']}/reschedule",
        headers=hp1,
        json={"starts_at": slots[1]["starts_at"]},
    )
    assert r.status_code == 200 and r.json()["starts_at"].startswith(slots[1]["starts_at"][:16])
    assert slots[0]["starts_at"] in [
        s["starts_at"] for s in await open_slots(client, hp1, did)
    ]  # old slot freed
    assert (
        await client.post(
            f"/api/appointments/{appt['id']}/reschedule",
            headers=hp1,
            json={"starts_at": slots[1]["starts_at"]},
        )
    ).status_code == 409
    assert (
        await client.post(f"/api/appointments/{appt['id']}/cancel", headers=hs)
    ).status_code == 200
    assert (
        await client.post(f"/api/appointments/{appt['id']}/cancel", headers=hs)
    ).status_code == 409
    assert (
        await client.post(
            f"/api/appointments/{appt['id']}/reschedule",
            headers=hs,
            json={"starts_at": slots[2]["starts_at"]},
        )
    ).status_code == 409
    assert slots[1]["starts_at"] in [
        s["starts_at"] for s in await open_slots(client, hp1, did)
    ]  # cancelled slot reopens


async def test_reschedule_conflicts_with_other_booking(client):
    hp1, hp2, did = (
        await login_headers(client, P1),
        await login_headers(client, P2),
        await doctor_id(),
    )
    slots = await open_slots(client, hp1, did)
    a1 = (await book(client, hp1, did, slots[0]["starts_at"])).json()
    await book(client, hp2, did, slots[1]["starts_at"])
    r = await client.post(
        f"/api/appointments/{a1['id']}/reschedule",
        headers=hp1,
        json={"starts_at": slots[1]["starts_at"]},
    )
    assert r.status_code == 409


async def test_complete_and_no_show_rules(client):
    hp, hd, hs, did = (
        await login_headers(client, P1),
        await login_headers(client, D1),
        await login_headers(client, S),
        await doctor_id(),
    )
    appt = (await book(client, hp, did, await first_slot(client, hp, did))).json()
    assert (
        await client.post(f"/api/appointments/{appt['id']}/complete", headers=hd)
    ).status_code == 409  # not started yet
    async with SessionLocal() as db:  # move it into the past
        a = await db.get(Appointment, uuid.UUID(appt["id"]))
        a.starts_at, a.ends_at = datetime.now(UTC) - timedelta(hours=1), datetime.now(
            UTC
        ) - timedelta(minutes=30)
        await db.commit()
    assert (
        await client.post(f"/api/appointments/{appt['id']}/complete", headers=hp)
    ).status_code == 403
    assert (
        await client.post(
            f"/api/appointments/{appt['id']}/complete", headers=await login_headers(client, D2)
        )
    ).status_code == 404
    assert (await client.post(f"/api/appointments/{appt['id']}/complete", headers=hd)).json()[
        "status"
    ] == "completed"
    assert (
        await client.post(f"/api/appointments/{appt['id']}/no-show", headers=hs)
    ).status_code == 409


async def test_no_show_by_staff(client):
    hp, hs, did = await login_headers(client, P1), await login_headers(client, S), await doctor_id()
    appt = (await book(client, hp, did, await first_slot(client, hp, did))).json()
    async with SessionLocal() as db:
        a = await db.get(Appointment, uuid.UUID(appt["id"]))
        a.starts_at, a.ends_at = datetime.now(UTC) - timedelta(hours=1), datetime.now(
            UTC
        ) - timedelta(minutes=30)
        await db.commit()
    assert (await client.post(f"/api/appointments/{appt['id']}/no-show", headers=hs)).json()[
        "status"
    ] == "no_show"


async def test_list_appointments_scoped_by_role(client):
    did = await doctor_id()
    hp1, hp2, hd, hd2, hs = [await login_headers(client, e) for e in (P1, P2, D1, D2, S)]
    await book(client, hp1, did, await first_slot(client, hp1, did))
    assert len((await client.get("/api/appointments", headers=hp1)).json()) == 1
    assert (await client.get("/api/appointments", headers=hp2)).json() == []
    assert len((await client.get("/api/appointments", headers=hd)).json()) == 1
    assert (await client.get("/api/appointments", headers=hd2)).json() == []
    assert (
        len(
            (
                await client.get(
                    "/api/appointments",
                    params={
                        "doctor_id": did,
                        "status": "booked",
                        "from": str(today()),
                        "to": str(today() + timedelta(days=30)),
                    },
                    headers=hs,
                )
            ).json()
        )
        == 1
    )
    # a patient cannot widen their view with query params
    assert (
        await client.get(
            "/api/appointments",
            params={"patient_id": str((await by_email(Patient, P1)).id)},
            headers=hp2,
        )
    ).json() == []


async def test_waitlist_notifies_next_patient_on_cancel(client, caplog):
    import logging

    hp1, hp2, hp3, did = [
        await login_headers(client, P1),
        await login_headers(client, P2),
        await login_headers(client, P3),
        await doctor_id(),
    ]
    start = await first_slot(client, hp1, did)
    appt = (await book(client, hp1, did, start)).json()
    day = datetime.fromisoformat(start).astimezone().date()
    from app.services.scheduling import local_date

    day = local_date(datetime.fromisoformat(start))
    w2 = await client.post(
        "/api/waitlist", headers=hp2, json={"doctor_id": did, "desired_date": str(day)}
    )
    await asyncio.sleep(0.01)
    await client.post(
        "/api/waitlist", headers=hp3, json={"doctor_id": did, "desired_date": str(day)}
    )
    assert w2.status_code == 201
    assert (
        await client.post(
            "/api/waitlist", headers=hp2, json={"doctor_id": did, "desired_date": str(day)}
        )
    ).json()["id"] == w2.json()[
        "id"
    ]  # no duplicates
    with caplog.at_level(logging.INFO, logger="app.email"):
        assert (
            await client.post(f"/api/appointments/{appt['id']}/cancel", headers=hp1)
        ).status_code == 200
    async with SessionLocal() as db:
        entries = {
            e.patient_id: e.status for e in (await db.execute(select(WaitlistEntry))).scalars()
        }
        notes = (
            (await db.execute(select(Notification).where(Notification.kind == "waitlist_slot")))
            .scalars()
            .all()
        )
    assert entries[(await by_email(Patient, P2)).id] == "notified"
    assert entries[(await by_email(Patient, P3)).id] == "waiting"
    p2_id = (await by_email(Patient, P2)).id
    assert {n.channel for n in notes} == {"email", "sms"}
    assert all(n.patient_id == p2_id for n in notes)
    # patient 2 books it and their waitlist entry is fulfilled
    assert (await book(client, hp2, did, start)).status_code == 201
    async with SessionLocal() as db:
        assert (await db.get(WaitlistEntry, uuid.UUID(w2.json()["id"]))).status == "fulfilled"


async def test_waitlist_validation_and_permissions(client):
    hp1, hp2, hs, did = (
        await login_headers(client, P1),
        await login_headers(client, P2),
        await login_headers(client, S),
        await doctor_id(),
    )
    assert (
        await client.post(
            "/api/waitlist", headers=hp1, json={"doctor_id": did, "desired_date": "2001-01-01"}
        )
    ).status_code == 422
    e = (
        await client.post(
            "/api/waitlist",
            headers=hp1,
            json={"doctor_id": did, "desired_date": str(today() + timedelta(days=3))},
        )
    ).json()
    assert len((await client.get("/api/waitlist", headers=hp1)).json()) == 1
    assert (await client.get("/api/waitlist", headers=hp2)).json() == []
    assert len((await client.get("/api/waitlist", headers=hs)).json()) == 1
    assert (await client.delete(f"/api/waitlist/{e['id']}", headers=hp2)).status_code == 404
    assert (await client.delete(f"/api/waitlist/{e['id']}", headers=hp1)).status_code == 204


async def test_availability_management_permissions(client):
    did = await doctor_id()
    tpl = [
        {"weekday": 0, "start_time": "08:00:00", "end_time": "12:00:00"},
        {"weekday": 0, "start_time": "13:00:00", "end_time": "16:00:00"},
    ]
    hd, hd2, hp, ha = (
        await login_headers(client, D1),
        await login_headers(client, D2),
        await login_headers(client, P1),
        await login_headers(client, ADMIN[0], ADMIN[1]),
    )
    assert (
        await client.put(f"/api/doctors/{did}/availability", json=tpl, headers=hp)
    ).status_code == 403
    assert (
        await client.put(f"/api/doctors/{did}/availability", json=tpl, headers=hd2)
    ).status_code == 403
    overlap = [
        {"weekday": 1, "start_time": "08:00:00", "end_time": "12:00:00"},
        {"weekday": 1, "start_time": "11:00:00", "end_time": "13:00:00"},
    ]
    assert (
        await client.put(f"/api/doctors/{did}/availability", json=overlap, headers=hd)
    ).status_code == 422
    bad = [{"weekday": 9, "start_time": "08:00:00", "end_time": "12:00:00"}]
    assert (
        await client.put(f"/api/doctors/{did}/availability", json=bad, headers=hd)
    ).status_code == 422
    assert (
        await client.put(f"/api/doctors/{did}/availability", json=tpl, headers=hd)
    ).status_code == 200
    got = (await client.get(f"/api/doctors/{did}/availability", headers=hp)).json()
    assert len(got) == 2
    slots = await open_slots(client, hp, did)
    assert all(
        datetime.fromisoformat(s["starts_at"])
        .astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata"))
        .weekday()
        == 0
        for s in slots
    )
    # restore weekly Mon-Fri 9-17 so other tests are unaffected
    restore = [{"weekday": d, "start_time": "09:00:00", "end_time": "17:00:00"} for d in range(5)]
    assert (
        await client.put(f"/api/doctors/{did}/availability", json=restore, headers=ha)
    ).status_code == 200
    assert (await client.get("/api/doctors", headers=hp)).status_code == 200
    assert len((await client.get("/api/departments", headers=hp)).json()) == 7
    assert (
        await client.get("/api/doctors", params={"department_id": 999}, headers=hp)
    ).json() == []


async def test_slots_range_validation(client):
    hp, did = await login_headers(client, P1), await doctor_id()
    r = await client.get(
        f"/api/doctors/{did}/slots", params={"from": "2030-01-01", "to": "2030-06-01"}, headers=hp
    )
    assert r.status_code == 422
    assert (
        await client.get(
            f"/api/doctors/{uuid.uuid4()}/slots",
            params={"from": "2030-01-01", "to": "2030-01-02"},
            headers=hp,
        )
    ).status_code == 404


async def test_db_exclusion_constraint_blocks_overlap_even_without_app_checks():
    did, pid = (await by_email(Doctor, D1)).id, (await by_email(Patient, P1)).id
    start = datetime.now(UTC) + timedelta(days=2)
    async with SessionLocal() as db:
        db.add(
            Appointment(
                patient_id=pid,
                doctor_id=did,
                starts_at=start,
                ends_at=start + timedelta(minutes=30),
            )
        )
        await db.commit()
    async with SessionLocal() as db:
        db.add(
            Appointment(
                patient_id=pid,
                doctor_id=did,
                starts_at=start + timedelta(minutes=10),
                ends_at=start + timedelta(minutes=40),
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
    async with SessionLocal() as db:  # cancelled rows do not block; adjacent slots are allowed
        db.add(
            Appointment(
                patient_id=pid,
                doctor_id=did,
                starts_at=start + timedelta(minutes=30),
                ends_at=start + timedelta(minutes=60),
            )
        )
        db.add(
            Appointment(
                patient_id=pid,
                doctor_id=did,
                starts_at=start,
                ends_at=start + timedelta(minutes=30),
                status="cancelled",
            )
        )
        await db.commit()


async def test_concurrent_booking_exactly_one_success(client):
    """50 parallel attempts (different patients) for one slot: exactly one 201, the rest 409."""
    hs, did = await login_headers(client, S), await doctor_id()
    start = await first_slot(client, hs, did)
    pids = []
    for i in range(50):
        r = await client.post(
            "/api/patients",
            headers=hs,
            json={"first_name": f"Load{i}", "last_name": "Tester", "date_of_birth": "1990-01-01"},
        )
        pids.append(r.json()["id"])
    results = await asyncio.gather(*[book(client, hs, did, start, patient_id=p) for p in pids])
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1 and codes.count(409) == 49, codes
    async with SessionLocal() as db:
        n = (
            await db.execute(
                select(func.count()).select_from(Appointment).where(Appointment.status == "booked")
            )
        ).scalar_one()
    assert n == 1


async def test_concurrent_booking_same_idempotency_key(client):
    hp, did = await login_headers(client, P1), await doctor_id()
    start = await first_slot(client, hp, did)
    results = await asyncio.gather(
        *[book(client, hp, did, start, key="same-key") for _ in range(10)]
    )
    assert {r.status_code for r in results} <= {200, 201, 409}
    async with SessionLocal() as db:
        assert (await db.execute(select(func.count()).select_from(Appointment))).scalar_one() == 1


async def test_reminder_windows_and_dedup(client):
    did, pid = (await by_email(Doctor, D1)).id, (await by_email(Patient, P1)).id
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        for hours in (23, 1, 30, 5):
            s = now + timedelta(hours=hours)
            db.add(
                Appointment(
                    patient_id=pid, doctor_id=did, starts_at=s, ends_at=s + timedelta(minutes=30)
                )
            )
        s = now + timedelta(hours=10)
        db.add(
            Appointment(
                patient_id=pid,
                doctor_id=did,
                starts_at=s,
                ends_at=s + timedelta(minutes=30),
                status="cancelled",
            )
        )
        await db.commit()
    async with SessionLocal() as db:
        assert (
            await send_due_reminders(db, now) == 3
        )  # 23h ->24h, 5h ->24h, 1h ->2h; 30h too early; cancelled skipped
        assert await send_due_reminders(db, now) == 0  # idempotent
        kinds = sorted(n.kind for n in (await db.execute(select(Notification))).scalars())
    assert kinds.count("reminder_24h") == 4 and kinds.count("reminder_2h") == 2  # 2 channels each
    # later the 23h appointment enters its 2h window and gets the second reminder
    async with SessionLocal() as db:
        assert await send_due_reminders(db, now + timedelta(hours=21, minutes=30)) >= 1


def test_reminder_kind_boundaries():
    now = datetime.now(UTC)
    assert reminder_kind(now, now + timedelta(hours=24)) == "24h"
    assert reminder_kind(now, now + timedelta(hours=24, minutes=1)) is None
    assert reminder_kind(now, now + timedelta(hours=2)) == "2h"
    assert reminder_kind(now, now - timedelta(minutes=1)) is None
    assert reminder_kind(now, now + timedelta(hours=2, minutes=1)) == "24h"


async def test_worker_tick_runs(client):
    from app.jobs.worker import reminder_tick

    await reminder_tick()
    async with SessionLocal() as db:
        assert (await db.execute(text("select 1"))).scalar_one() == 1
