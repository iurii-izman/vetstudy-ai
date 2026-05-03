from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
import threading
import time


def hash_password(password: str, *, salt: str | None = None, iterations: int = 310000) -> str:
    local_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), local_salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${local_salt}${base64.b64encode(digest).decode('ascii')}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iteration_raw, salt, digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iteration_raw)
    except ValueError:
        return False
    expected = hash_password(password, salt=salt, iterations=iterations)
    return hmac.compare_digest(expected, encoded)


@dataclass(frozen=True)
class SessionToken:
    token: str
    expires_at: datetime
    session_id: str


def issue_session_token(*, secret: str, telegram_user_id: int, role: str, ttl_seconds: int = 900, session_id: str | None = None) -> SessionToken:
    sid = session_id or secrets.token_urlsafe(18)
    expires_at = datetime.now(UTC) + timedelta(seconds=max(60, ttl_seconds))
    payload = f"{telegram_user_id}:{role}:{sid}:{int(expires_at.timestamp())}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(f"{payload}:{sig}".encode("utf-8")).decode("ascii")
    return SessionToken(token=token, expires_at=expires_at, session_id=sid)


def validate_session_token(token: str, *, secret: str) -> tuple[int, str, str]:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        telegram_raw, role, session_id, exp_raw, sig = decoded.split(":", 4)
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("malformed token") from exc
    payload = f"{telegram_raw}:{role}:{session_id}:{exp_raw}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise ValueError("invalid signature")
    if int(exp_raw) < int(datetime.now(UTC).timestamp()):
        raise ValueError("expired")
    return int(telegram_raw), role, session_id


class InMemoryRateLimiter:
    def __init__(self):
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            bucket = [ts for ts in self._buckets.get(key, []) if now - ts < window_seconds]
            if len(bucket) >= limit:
                self._buckets[key] = bucket
                return False
            bucket.append(now)
            self._buckets[key] = bucket
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets = {}
