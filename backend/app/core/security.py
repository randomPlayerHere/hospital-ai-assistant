from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from starlette.concurrency import run_in_threadpool

# OWASP Password Storage Cheat Sheet minimum profile for argon2id (19 MiB, t=2, p=1). Stored hashes carry
# their own parameters, so this can be raised later without invalidating existing passwords.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


async def hash_password_async(password: str) -> str:
    """argon2 is CPU-heavy by design; keep it off the event loop."""
    return await run_in_threadpool(hash_password, password)


async def verify_password_async(password: str, hashed: str) -> bool:
    return await run_in_threadpool(verify_password, password, hashed)
