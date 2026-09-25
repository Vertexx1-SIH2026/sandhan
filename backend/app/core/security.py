"""
security.py
- JWT issuing/decoding for role + case-scoped claims (OAuth2/JWT + RBAC).
- Password hashing.
- SHA-256 file hashing and a per-case Merkle tree, used by the evidence
  chain-of-custody pipeline.

Changes vs. the first prototype:
- python-jose -> PyJWT (python-jose is unmaintained and has open CVEs; PyJWT is
  what the FastAPI docs now recommend).
- passlib+bcrypt -> stdlib PBKDF2-SHA256. passlib 1.7.4 breaks with
  bcrypt>=4.1, which was the most common "pip install worked but login
  crashes" failure. Old bcrypt hashes are still accepted if the `bcrypt`
  package happens to be installed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import settings

ALGORITHM = "HS256"
_PBKDF2_ITERATIONS = 240_000


# ----------------------------------------------------------------------
# Passwords
# ----------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iters, salt_b64, dk_b64 = password_hash.split("$")
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), base64.b64decode(salt_b64), int(iters)
            )
            return hmac.compare_digest(dk, base64.b64decode(dk_b64))
        except (ValueError, TypeError):
            return False
    if password_hash.startswith("$2"):  # legacy bcrypt hash from the first prototype
        try:
            import bcrypt  # type: ignore

            return bcrypt.checkpw(password.encode(), password_hash.encode())
        except Exception:
            return False
    return False


# ----------------------------------------------------------------------
# JWT
# ----------------------------------------------------------------------
def create_access_token(claims: dict[str, Any]) -> str:
    to_encode = claims.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(
        minutes=settings.SANDHAN_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    return jwt.encode(to_encode, settings.SANDHAN_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.SANDHAN_SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


# ----------------------------------------------------------------------
# Hashing / Merkle tree (per case)
# ----------------------------------------------------------------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def merkle_root(leaf_hashes: list[str]) -> str:
    """
    Builds a Merkle tree over one case's file hashes and returns the root.
    Every file in the case is a leaf; any change to any file changes the root,
    which the BSA Sec.63 evidence certificate embeds as text + QR code.
    """
    if not leaf_hashes:
        return sha256_bytes(b"")

    level = [bytes.fromhex(h) for h in sorted(leaf_hashes)]
    if len(level) == 1:
        return hashlib.sha256(level[0]).hexdigest()

    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(hashlib.sha256(left + right).digest())
        level = nxt
    return level[0].hex()
