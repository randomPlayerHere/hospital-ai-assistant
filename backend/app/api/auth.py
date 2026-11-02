from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.ratelimit import AUTH_LIMIT, limiter
from app.core.security import hash_password_async, verify_password_async
from app.core.tokens import REFRESH_TTL
from app.models import Patient, User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MFADisableRequest,
    MFAEnableRequest,
    MFASetupResponse,
    MFAVerifyLoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
    UserOut,
)
from app.services import auth as svc
from app.services.email import send_email
from app.services.mfa import generate_totp_secret, get_totp_uri, verify_totp

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=u.role.name,
        is_active=u.is_active,
        mfa_enabled=bool(u.mfa_enabled),
    )


def _set_refresh_cookie(response: Response, refresh_token: str | None) -> None:
    if refresh_token:
        s = get_settings()
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            samesite="lax",
            secure=(s.environment == "prod"),
            path="/api/auth",
            max_age=int(REFRESH_TTL.total_seconds()),
        )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
@limiter.limit(AUTH_LIMIT)
async def register(
    request: Request,
    response: Response,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    email = body.email.lower()
    if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    role = await svc.get_role(db, "patient")
    user = User(
        email=email,
        password_hash=await hash_password_async(body.password),
        full_name=f"{body.first_name} {body.last_name}",
        role_id=role.id,
    )
    db.add(user)
    await db.flush()
    db.add(
        Patient(
            user_id=user.id,
            first_name=body.first_name,
            last_name=body.last_name,
            date_of_birth=body.date_of_birth,
            phone=body.phone,
            email=email,
        )
    )
    await db.commit()
    await db.refresh(user)
    tokens = await svc.issue_tokens(db, user)
    _set_refresh_cookie(response, tokens.get("refresh_token"))
    return tokens


@router.post("/login", response_model=TokenPair)
@limiter.limit(AUTH_LIMIT)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    user = await svc.authenticate(db, body.email, body.password)
    if user.mfa_enabled:
        return TokenPair(
            mfa_required=True,
            mfa_ticket=svc.create_mfa_ticket(user.id),
        )
    tokens = await svc.issue_tokens(db, user)
    _set_refresh_cookie(response, tokens.get("refresh_token"))
    return tokens


@router.post("/mfa/verify-login", response_model=TokenPair)
@limiter.limit(AUTH_LIMIT)
async def verify_mfa_login(
    request: Request,
    response: Response,
    body: MFAVerifyLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    user_id = svc.decode_mfa_ticket(body.mfa_ticket)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active or not user.mfa_enabled or not user.totp_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA session")
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid two-factor authentication code")
    tokens = await svc.issue_tokens(db, user)
    _set_refresh_cookie(response, tokens.get("refresh_token"))
    return tokens


@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(user: User = Depends(get_current_user)) -> MFASetupResponse:
    secret = generate_totp_secret()
    uri = get_totp_uri(secret, user.email)
    return MFASetupResponse(secret=secret, otpauth_url=uri)


@router.post("/mfa/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_mfa(
    body: MFAEnableRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    if not verify_totp(body.secret, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid two-factor authentication code")
    user.totp_secret = body.secret
    user.mfa_enabled = True
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_mfa(
    body: MFADisableRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    if not await verify_password_async(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid current password")
    if user.totp_secret and not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid two-factor authentication code")
    user.totp_secret = None
    user.mfa_enabled = False
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/refresh", response_model=TokenPair)
@limiter.limit(AUTH_LIMIT)
async def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest = RefreshRequest(),
    db: AsyncSession = Depends(get_db),
):
    token = body.refresh_token or request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")
    tokens = await svc.rotate_refresh(db, token)
    _set_refresh_cookie(response, tokens.get("refresh_token"))
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    body: RefreshRequest = RefreshRequest(),
    db: AsyncSession = Depends(get_db),
) -> Response:
    token = body.refresh_token or request.cookies.get("refresh_token")
    if token:
        await svc.revoke_refresh(db, token)
    response.delete_cookie("refresh_token", path="/api/auth")
    return response


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(AUTH_LIMIT)
async def forgot_password(
    request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    user = (
        await db.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if user and user.is_active:
        raw = await svc.create_reset_token(db, user)
        send_email(user.email, "Password reset", f"Use this token to reset your password: {raw}")
    # Same response either way: never reveal whether an account exists.
    return {"detail": "If the account exists, a reset email has been sent."}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(AUTH_LIMIT)
async def reset_password(
    request: Request, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> Response:
    await svc.consume_reset_token(db, body.token, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(AUTH_LIMIT)
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    await svc.change_password(db, user, body.current_password, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return user_out(user)
