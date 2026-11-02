import json
from pathlib import Path
import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import AuditSessionLocal
from app.models import AuditLog
from app.scripts.verify_audit_chain import verify_chain
from tests.conftest import ADMIN, login_headers


async def test_audit_hash_chain_and_verification(client):
    h = await login_headers(client, ADMIN[0], ADMIN[1])

    # Perform a sequence of audited API actions
    await client.get("/api/auth/me", headers=h)
    await client.get("/api/admin/users", headers=h)
    await client.get("/api/admin/analytics/overview", headers=h)

    # Verify chain
    ok, count, msg = await verify_chain()
    assert ok is True
    assert count >= 3
    assert "Chain intact" in msg

    # Inspect records
    async with AuditSessionLocal() as db:
        rows = (
            await db.execute(select(AuditLog).order_by(AuditLog.id.asc()))
        ).scalars().all()
        assert len(rows) >= 3
        # First row after truncate has prev_hash = None
        # Subsequent rows have prev_hash == prior row's entry_hash
        for i in range(1, len(rows)):
            assert rows[i].prev_hash == rows[i - 1].entry_hash


async def test_audit_tamper_detection(client):
    h = await login_headers(client, ADMIN[0], ADMIN[1])
    await client.get("/api/auth/me", headers=h)
    await client.get("/api/admin/users", headers=h)

    # Intentionally tamper with an audit log row in the database
    async with AuditSessionLocal() as db:
        first_row = (
            await db.execute(select(AuditLog).order_by(AuditLog.id.asc()).limit(1))
        ).scalar_one()
        await db.execute(
            update(AuditLog)
            .where(AuditLog.id == first_row.id)
            .values(path="/api/tampered-path")
        )
        await db.commit()

    # Verification must detect the tampering
    ok, bad_id, msg = await verify_chain()
    assert ok is False
    assert bad_id == first_row.id
    assert "Tampered record id" in msg


async def test_audit_external_streaming(client, tmp_path):
    stream_file = tmp_path / "audit_stream.jsonl"
    s = get_settings()
    old_stream = s.audit_log_stream_path
    try:
        s.audit_log_stream_path = str(stream_file)

        h = await login_headers(client, ADMIN[0], ADMIN[1])
        await client.get("/api/auth/me", headers=h)

        assert stream_file.exists()
        lines = stream_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        data = json.loads(lines[-1])
        assert data["resource_type"] == "auth/me"
        assert "entry_hash" in data
        assert "prev_hash" in data
    finally:
        s.audit_log_stream_path = old_stream
