import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.ratelimit import limiter
from app.models import AuditLog
from tests.conftest import ADMIN, PASSWORD, login_headers

REG = {"password": "Str0ng!Password1", "first_name": "Test", "last_name": "User",
       "date_of_birth": "1990-01-01"}  # fmt: skip


async def test_register_login_me(client, unique_email):
    email = unique_email()
    r = await client.post("/api/auth/register", json={**REG, "email": email})
    assert r.status_code == 201
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await client.get("/api/auth/me", headers=h)).json()
    assert me["role"] == "patient" and me["email"] == email
    assert (await client.get("/api/patients/me", headers=h)).status_code == 200


async def test_register_rejects_weak_password_and_duplicate(client, unique_email):
    email = unique_email()
    assert (
        await client.post("/api/auth/register", json={**REG, "email": email, "password": "short"})
    ).status_code == 422
    assert (
        await client.post("/api/auth/register", json={**REG, "email": email})
    ).status_code == 201
    assert (
        await client.post("/api/auth/register", json={**REG, "email": email})
    ).status_code == 409


async def test_login_wrong_password_and_unknown_user(client):
    r = await client.post(
        "/api/auth/login", json={"email": ADMIN[0], "password": "wrong-password-1"}
    )
    assert r.status_code == 401
    r = await client.post(
        "/api/auth/login", json={"email": "nobody@x.dev", "password": "whatever-123456"}
    )
    assert r.status_code == 401


async def test_lockout_after_repeated_failures(client):
    bad = {"email": "staff@hospital.example.com", "password": "wrong-password-1"}
    for _ in range(5):
        assert (await client.post("/api/auth/login", json=bad)).status_code == 401
    good = {"email": "staff@hospital.example.com", "password": PASSWORD}
    assert (await client.post("/api/auth/login", json=good)).status_code == 423


async def test_refresh_rotation_and_reuse_detection(client):
    tokens = (
        await client.post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    ).json()
    r1 = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    # replaying the old token fails and revokes the new one too
    assert (
        await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401
    assert (
        await client.post("/api/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]})
    ).status_code == 401


async def test_logout_revokes_refresh(client):
    tokens = (
        await client.post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    ).json()
    assert (
        await client.post("/api/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 204
    assert (
        await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401


async def test_password_reset_flow(client, unique_email, caplog):
    import logging

    email = unique_email()
    await client.post("/api/auth/register", json={**REG, "email": email})
    with caplog.at_level(logging.INFO, logger="app.email"):
        r = await client.post("/api/auth/forgot-password", json={"email": email})
    assert r.status_code == 202
    token = [r for r in caplog.records if r.name == "app.email"][-1].body.split(": ")[-1]
    assert (
        await client.post(
            "/api/auth/reset-password", json={"token": token, "new_password": "N3w!Password99"}
        )
    ).status_code == 204
    assert (
        await client.post(
            "/api/auth/reset-password", json={"token": token, "new_password": "N3w!Password99"}
        )
    ).status_code == 400
    assert (
        await client.post("/api/auth/login", json={"email": email, "password": "N3w!Password99"})
    ).status_code == 200
    # unknown email gives the same response
    assert (
        await client.post("/api/auth/forgot-password", json={"email": "nope@x.dev"})
    ).status_code == 202


async def test_invalid_and_missing_token(client):
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (
        await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    ).status_code == 401


async def test_rate_limit_on_auth_endpoints(client):
    limiter.enabled = True
    limiter.reset()
    body = {"email": "a@b.dev", "password": "x" * 12}
    try:
        responses = [await client.post("/api/auth/login", json=body) for _ in range(12)]
    finally:
        limiter.enabled = False
    limited = [r for r in responses if r.status_code == 429]
    assert limited
    assert limited[0].json() == {"detail": "Too many requests. Please wait a minute and try again."}
    assert limited[0].headers["retry-after"] == "60"


async def test_audit_log_records_access(client):
    h = await login_headers(client, ADMIN[0], ADMIN[1])
    await client.get("/api/admin/users", headers=h)
    async with SessionLocal() as db:
        rows = (
            (await db.execute(select(AuditLog).where(AuditLog.resource_type == "admin/users")))
            .scalars()
            .all()
        )
    assert rows and rows[0].action == "read" and rows[0].role == "admin" and rows[0].user_id


@pytest.mark.parametrize(
    "email", ["staff@hospital.example.com", "doctor1@hospital.example.com", "patient1@example.com"]
)
async def test_admin_endpoints_forbidden_for_non_admins(client, email):
    h = await login_headers(client, email)
    assert (await client.get("/api/admin/users", headers=h)).status_code == 403
    body = {"email": "x@y.dev", "password": "Str0ng!Password1", "full_name": "X", "role": "staff"}
    assert (await client.post("/api/admin/users", json=body, headers=h)).status_code == 403


async def test_admin_creates_users(client, unique_email):
    h = await login_headers(client, ADMIN[0], ADMIN[1])
    email = unique_email()
    r = await client.post(
        "/api/admin/users",
        headers=h,
        json={"email": email, "password": "Str0ng!Password1", "full_name": "S", "role": "staff"},
    )
    assert r.status_code == 201 and r.json()["role"] == "staff"
    # doctor requires a department
    r = await client.post(
        "/api/admin/users",
        headers=h,
        json={
            "email": unique_email(),
            "password": "Str0ng!Password1",
            "full_name": "D",
            "role": "doctor",
        },
    )
    assert r.status_code == 422
    # deactivated user cannot use an existing token
    uid = r.json and (await client.get("/api/admin/users", headers=h)).json()
    target = next(u for u in uid if u["email"] == email)
    assert (
        await client.patch(
            f"/api/admin/users/{target['id']}/active", params={"active": "false"}, headers=h
        )
    ).status_code == 200
    assert (
        await client.post("/api/auth/login", json={"email": email, "password": "Str0ng!Password1"})
    ).status_code == 401


def test_audit_resource_parsing():
    from app.core.audit import _parse_resource

    pid = "6f1c1c0e-0000-4000-8000-000000000001"
    assert _parse_resource("/api/patients") == ("patients", None)
    assert _parse_resource(f"/api/patients/{pid}") == ("patients", pid)
    assert _parse_resource(f"/api/patients/{pid}/visits") == ("patients/visits", pid)
    assert _parse_resource("/api/admin/users") == ("admin/users", None)
    assert _parse_resource(f"/api/visits/{pid}/prescriptions") == ("visits/prescriptions", pid)
    assert _parse_resource("/api/auth/login") == ("auth/login", None)


async def test_audit_ignores_spoofed_forwarded_for_header(client):
    from sqlalchemy import select as sel

    await client.get("/api/auth/me", headers={"X-Forwarded-For": "6.6.6.6"})
    async with SessionLocal() as db:
        ips = {r.ip for r in (await db.execute(sel(AuditLog))).scalars()}
    assert "6.6.6.6" not in ips


async def test_admin_manages_departments(client):
    h = await login_headers(client, ADMIN[0], ADMIN[1])
    r = await client.post(
        "/api/admin/departments", headers=h, json={"name": "Oncology", "description": "Cancer care"}
    )
    assert r.status_code == 201
    did = r.json()["id"]
    assert (
        await client.post("/api/admin/departments", headers=h, json={"name": "oncology"})
    ).status_code == 409
    assert (
        await client.put(
            f"/api/admin/departments/{did}", headers=h, json={"name": "Oncology & Haematology"}
        )
    ).json()["name"] == "Oncology & Haematology"
    assert (
        await client.put(f"/api/admin/departments/{did}", headers=h, json={"name": "Cardiology"})
    ).status_code == 409
    assert (
        await client.put("/api/admin/departments/99999", headers=h, json={"name": "Nope"})
    ).status_code == 404
    assert (
        await client.post("/api/admin/departments", headers=h, json={"name": "x"})
    ).status_code == 422
    hs = await login_headers(client, "staff@hospital.example.com")
    assert (
        await client.post("/api/admin/departments", headers=hs, json={"name": "Sneaky"})
    ).status_code == 403
    async with SessionLocal() as db:  # keep the seeded department set stable for other tests
        from app.models import Department

        await db.delete(await db.get(Department, did))
        await db.commit()

async def test_change_password_success_and_revocation(client, unique_email):
    email = unique_email()
    reg = await client.post("/api/auth/register", json={**REG, "email": email})
    tokens = reg.json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}

    # Unauthenticated rejected
    assert (
        await client.post(
            "/api/auth/change-password",
            json={"current_password": REG["password"], "new_password": "NewStrong!Pass123"},
        )
    ).status_code == 401

    # Wrong current password rejected
    bad_cur = await client.post(
        "/api/auth/change-password",
        headers=h,
        json={"current_password": "wrong-current-pw", "new_password": "NewStrong!Pass123"},
    )
    assert bad_cur.status_code == 400
    assert "Current password incorrect" in bad_cur.json()["detail"]

    # Short new password rejected
    assert (
        await client.post(
            "/api/auth/change-password",
            headers=h,
            json={"current_password": REG["password"], "new_password": "short"},
        )
    ).status_code == 422

    # Successful password change
    res = await client.post(
        "/api/auth/change-password",
        headers=h,
        json={"current_password": REG["password"], "new_password": "NewStrong!Pass123"},
    )
    assert res.status_code == 204

    # Old password no longer works
    assert (
        await client.post(
            "/api/auth/login", json={"email": email, "password": REG["password"]}
        )
    ).status_code == 401

    # Old refresh token revoked
    assert (
        await client.post(
            "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
    ).status_code == 401

    # New password works to log in
    login_new = await client.post(
        "/api/auth/login", json={"email": email, "password": "NewStrong!Pass123"}
    )
    assert login_new.status_code == 200



async def test_refresh_token_cookie_flow(client, unique_email):
    email = unique_email()
    reg = await client.post("/api/auth/register", json={**REG, "email": email})
    assert reg.status_code == 201
    assert "set-cookie" in reg.headers
    assert "refresh_token=" in reg.headers["set-cookie"]
    assert "httponly" in reg.headers["set-cookie"].lower()

    # Login sets cookie
    login_res = await client.post(
        "/api/auth/login", json={"email": email, "password": REG["password"]}
    )
    assert login_res.status_code == 200
    assert "set-cookie" in login_res.headers
    cookie_str = login_res.headers["set-cookie"]
    assert "refresh_token=" in cookie_str

    # Refresh using cookie without body
    ref_res = await client.post("/api/auth/refresh")
    assert ref_res.status_code == 200
    ref_data = ref_res.json()
    assert ref_data["access_token"] is not None
    assert "refresh_token=" in ref_res.headers["set-cookie"]

    # Logout clears cookie
    logout_res = await client.post("/api/auth/logout")
    assert logout_res.status_code == 204
    assert "refresh_token="";" in logout_res.headers.get("set-cookie", "") or "max-age=0" in logout_res.headers.get("set-cookie", "").lower()
