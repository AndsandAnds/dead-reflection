from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))


def hash_password(password: str, *, iterations: int = 210_000) -> str:
    """
    PBKDF2-SHA256 password hash:
      pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
    """
    if not password:
        raise ValueError("password must be non-empty")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=32
    )
    return f"pbkdf2_sha256${iterations}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iters_s, salt_b64, hash_b64 = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        salt = _b64d(salt_b64)
        expected = _b64d(hash_b64)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iters, dklen=len(expected)
        )
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def new_session_token() -> str:
    # Cookie value (opaque bearer token).
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    # Store only a hash in DB to reduce blast radius if DB is copied.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


