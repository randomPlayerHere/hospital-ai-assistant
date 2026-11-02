"""Audit log hash-chain verification tool.

Usage:
  python -m app.scripts.verify_audit_chain
"""

import asyncio

from sqlalchemy import select

from app.core.audit import compute_entry_hash
from app.core.db import AuditSessionLocal
from app.models import AuditLog


async def verify_chain() -> tuple[bool, int, str]:
    async with AuditSessionLocal() as db:
        rows = (
            await db.execute(select(AuditLog).order_by(AuditLog.id.asc()))
        ).scalars().all()

        if not rows:
            return True, 0, "No audit log records found."

        prev_hash = None
        for r in rows:
            if r.prev_hash != prev_hash:
                return (
                    False,
                    r.id,
                    f"Chain broken at record id {r.id}: expected prev_hash '{prev_hash}', got '{r.prev_hash}'",
                )
            expected_entry = compute_entry_hash(
                prev_hash=r.prev_hash,
                user_id=r.user_id,
                role=r.role,
                action=r.action,
                resource_type=r.resource_type,
                resource_id=r.resource_id,
                method=r.method,
                path=r.path,
                status_code=r.status_code,
                ip=r.ip,
                request_id=r.request_id,
            )
            if r.entry_hash != expected_entry:
                return (
                    False,
                    r.id,
                    f"Tampered record id {r.id}: payload does not match entry_hash.",
                )
            prev_hash = r.entry_hash

        return True, len(rows), f"All {len(rows)} audit records verified successfully. Chain intact."


if __name__ == "__main__":
    ok, count, msg = asyncio.run(verify_chain())
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    if not ok:
        raise SystemExit(1)
