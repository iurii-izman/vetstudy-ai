import hashlib
import hmac
import time
from dataclasses import dataclass

from app.config import get_settings

CALLBACK_TTL_BUCKETS = 12
CALLBACK_BUCKET_SECONDS = 300


@dataclass(frozen=True)
class ActionCallback:
    action: str
    payload: str = ""


def callback_secret() -> str:
    settings = get_settings()
    return getattr(settings, "user_id_hash_salt", "") or getattr(settings, "web_owner_token", "") or "dev-callback-secret"


def callback_signature(action: str, payload: str, bucket: int) -> str:
    raw = f"{action}:{payload}:{bucket}".encode("utf-8")
    return hmac.new(callback_secret().encode("utf-8"), raw, hashlib.sha256).hexdigest()[:10]


def callback_data(action: str, payload: str = "") -> str:
    bucket = int(time.time() // CALLBACK_BUCKET_SECONDS)
    return f"vx:{action}:{payload}:{callback_signature(action, payload, bucket)}"


def valid_callback_signature(action: str, payload: str, signature: str) -> bool:
    current = int(time.time() // CALLBACK_BUCKET_SECONDS)
    for bucket in range(current, current - CALLBACK_TTL_BUCKETS - 1, -1):
        if hmac.compare_digest(signature, callback_signature(action, payload, bucket)):
            return True
    return False


def parse_callback_data(data: str) -> ActionCallback | None:
    if not data.startswith("vx:"):
        return None
    parts = data.split(":", 3)
    if len(parts) != 4:
        return None
    _, action, payload, signature = parts
    if not action:
        return None
    if not valid_callback_signature(action, payload, signature):
        return None
    return ActionCallback(action=action, payload=payload)
