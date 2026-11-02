import hashlib
import json
import logging
import re
import uuid
from pathlib import Path

import jwt
from sqlalchemy import select
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.db import AuditSessionLocal
from app.core.tokens import decode_access_token
from app.models import AuditLog

log = logging.getLogger("app.audit")
_ACTIONS = {"GET": "read", "POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def _parse_resource(path: str) -> tuple[str, str | None]:
    """'/api/patients/<id>/visits' -> ('patients/visits', '<id>'): names of path segments, first id."""
    parts = [p for p in path.split("/") if p][1:]  # drop leading "api"
    names = [p for p in parts if not _UUID.match(p)][:3]
    resource_id = next((p for p in parts if _UUID.match(p)), None)
    return "/".join(names) or "unknown", resource_id


def compute_entry_hash(
    prev_hash: str | None,
    user_id: uuid.UUID | None,
    role: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    method: str,
    path: str,
    status_code: int,
    ip: str | None,
    request_id: str | None,
) -> str:
    raw = (
        f"{prev_hash or 'GENESIS'}|{user_id}|{role}|{action}|{resource_type}|"
        f"{resource_id}|{method}|{path}|{status_code}|{ip}|{request_id}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AuditMiddleware:
    """Records every /api request (user, action, resource, status, IP) in audit_logs.

    Pure ASGI: the row is written after the response has been sent, so it adds no client latency.
    Includes cryptographic hash chaining and optional append-only file streaming.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            await self._record(scope, path, holder["status"])

    async def _record(self, scope: Scope, path: str, status_code: int) -> None:
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope["headers"]}
        user_id: uuid.UUID | None = None
        role: str | None = None
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                payload = decode_access_token(auth[7:])
                user_id, role = uuid.UUID(payload["sub"]), payload.get("role")
            except (jwt.PyJWTError, KeyError, ValueError):
                pass
        resource, resource_id = _parse_resource(path)
        method = scope["method"]
        action = "auth" if resource.startswith("auth") else _ACTIONS.get(method, "read")
        client = scope.get("client")
        ip = client[0] if client else None
        req_id = scope.get("state", {}).get("request_id")

        try:
            s = get_settings()
            async with AuditSessionLocal() as db:
                latest = (
                    await db.execute(
                        select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1)
                    )
                ).scalar_one_or_none()
                prev_hash = latest

                entry_hash = compute_entry_hash(
                    prev_hash=prev_hash,
                    user_id=user_id,
                    role=role,
                    action=action,
                    resource_type=resource,
                    resource_id=resource_id,
                    method=method,
                    path=path[:300],
                    status_code=status_code,
                    ip=ip,
                    request_id=req_id,
                )

                db.add(
                    AuditLog(
                        user_id=user_id,
                        role=role,
                        action=action,
                        resource_type=resource,
                        resource_id=resource_id,
                        method=method,
                        path=path[:300],
                        status_code=status_code,
                        ip=ip,
                        request_id=req_id,
                        prev_hash=prev_hash,
                        entry_hash=entry_hash,
                    )
                )
                await db.commit()

            # Optional external streaming (append-only JSONL log file for write-once / external SIEM collector)
            if s.audit_log_stream_path:
                payload = {
                    "user_id": str(user_id) if user_id else None,
                    "role": role,
                    "action": action,
                    "resource_type": resource,
                    "resource_id": resource_id,
                    "method": method,
                    "path": path[:300],
                    "status_code": status_code,
                    "ip": ip,
                    "request_id": req_id,
                    "prev_hash": prev_hash,
                    "entry_hash": entry_hash,
                }
                p = Path(s.audit_log_stream_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(payload) + "\n")
        except Exception:
            # Never break the user's request, but make the gap visible to operators.
            log.exception("audit log write failed")
