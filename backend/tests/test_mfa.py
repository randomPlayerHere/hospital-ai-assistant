import pytest

from app.services.mfa import generate_totp_secret, get_totp_code, get_totp_uri, verify_totp
from tests.conftest import ADMIN, login_headers


def test_totp_unit_helpers():
    secret = generate_totp_secret()
    assert len(secret) >= 26
    uri = get_totp_uri(secret, "admin@hospital.example.com", "Hospital AI")
    assert f"secret={secret}" in uri
    assert "Hospital" in uri

    code = get_totp_code(secret)
    assert len(code) == 6 and code.isdigit()
    assert verify_totp(secret, code)
    assert not verify_totp(secret, "000000" if code != "000000" else "111111")
    assert not verify_totp(secret, "abc")
    assert not verify_totp(secret, "")


async def test_mfa_setup_enable_and_login_lifecycle(client):
    admin_email, admin_pw = ADMIN
    h = await login_headers(client, admin_email, admin_pw)

    # 1. Initially mfa_enabled is False
    me_res = await client.get("/api/auth/me", headers=h)
    assert me_res.status_code == 200
    assert me_res.json()["mfa_enabled"] is False

    # 2. Setup MFA
    setup_res = await client.post("/api/auth/mfa/setup", headers=h)
    assert setup_res.status_code == 200
    setup_data = setup_res.json()
    secret = setup_data["secret"]
    assert "otpauth_url" in setup_data

    # 3. Enable with invalid code fails
    bad_enable = await client.post(
        "/api/auth/mfa/enable",
        headers=h,
        json={"secret": secret, "code": "000000"},
    )
    assert bad_enable.status_code == 400

    # 4. Enable with valid TOTP code succeeds
    valid_code = get_totp_code(secret)
    good_enable = await client.post(
        "/api/auth/mfa/enable",
        headers=h,
        json={"secret": secret, "code": valid_code},
    )
    assert good_enable.status_code == 204

    # 5. Verify /api/auth/me shows mfa_enabled = True
    me_after = await client.get("/api/auth/me", headers=h)
    assert me_after.json()["mfa_enabled"] is True

    # 6. Next login requires MFA ticket
    login_res = await client.post(
        "/api/auth/login",
        json={"email": admin_email, "password": admin_pw},
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["mfa_required"] is True
    assert login_data["access_token"] is None
    ticket = login_data["mfa_ticket"]
    assert ticket is not None

    # 7. Verify login with wrong code fails
    bad_verify = await client.post(
        "/api/auth/mfa/verify-login",
        json={"mfa_ticket": ticket, "code": "111111"},
    )
    assert bad_verify.status_code == 401

    # 8. Verify login with valid code returns full token pair
    cur_code = get_totp_code(secret)
    good_verify = await client.post(
        "/api/auth/mfa/verify-login",
        json={"mfa_ticket": ticket, "code": cur_code},
    )
    assert good_verify.status_code == 200
    pair = good_verify.json()
    assert pair["mfa_required"] is False
    assert pair["access_token"] is not None

    # 9. Verify access token works
    new_h = {"Authorization": f"Bearer {pair['access_token']}"}
    assert (await client.get("/api/auth/me", headers=new_h)).status_code == 200

    # 10. Disable MFA
    bad_pw_disable = await client.post(
        "/api/auth/mfa/disable",
        headers=new_h,
        json={"password": "WrongPassword!123", "code": get_totp_code(secret)},
    )
    assert bad_pw_disable.status_code == 401

    disable_res = await client.post(
        "/api/auth/mfa/disable",
        headers=new_h,
        json={"password": admin_pw, "code": get_totp_code(secret)},
    )
    assert disable_res.status_code == 204

    # 11. Normal login works directly without MFA
    direct_login = await client.post(
        "/api/auth/login",
        json={"email": admin_email, "password": admin_pw},
    )
    assert direct_login.status_code == 200
    assert direct_login.json()["mfa_required"] is False
    assert direct_login.json()["access_token"] is not None


async def test_mfa_ticket_invalid_rejected(client):
    res = await client.post(
        "/api/auth/mfa/verify-login",
        json={"mfa_ticket": "garbage-ticket-data", "code": "123456"},
    )
    assert res.status_code == 401
