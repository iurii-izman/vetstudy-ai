from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def get_request_id() -> str:
    return request_id_ctx.get()


def safe_user_id(user_id: int | str | None, salt: str = "") -> str:
    if user_id is None:
        return "-"
    raw = f"{salt}:{user_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
        }
        for key in (
            "event",
            "status",
            "provider",
            "model",
            "purpose",
            "route_decision",
            "reason",
            "fallback_used",
            "breaker_state",
            "failures",
            "open_remaining_ms",
            "latency_ms",
            "error_category",
            "telegram_user_id",
            "path",
            "method",
            "status_code",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_vetstudy_logging_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    root._vetstudy_logging_configured = True


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_ctx.set(request_id)
        t0 = time.perf_counter()
        response = await call_next(request)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        response.headers["X-Request-ID"] = request_id
        logging.getLogger("app.http").info(
            "http_request",
            extra={
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        return response
