from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import socket
from typing import Any
from uuid import UUID

from redis.asyncio import from_url as redis_from_url
from redis.exceptions import ResponseError

from app.config import get_settings

logger = logging.getLogger("app.media.jobs")

DOCUMENT_INDEX_KIND = "document_index"
DEFAULT_STREAM = "media:document_index_jobs"
DEFAULT_GROUP = "media-indexers"
DEFAULT_BLOCK_MS = 1000
DEFAULT_RECLAIM_IDLE_MS = 900_000

_worker_task: asyncio.Task | None = None


@dataclass(frozen=True)
class DocumentIndexJob:
    job_id: str
    stored_path: str
    original_name: str
    user_id: str
    topic_id: str
    telegram_user_id: int
    display_name: str | None = None
    retry_count: int = 0

    def to_fields(self) -> dict[str, str]:
        return {
            "kind": DOCUMENT_INDEX_KIND,
            "version": "1",
            "job_id": self.job_id,
            "stored_path": self.stored_path,
            "original_name": self.original_name,
            "user_id": self.user_id,
            "topic_id": self.topic_id,
            "telegram_user_id": str(self.telegram_user_id),
            "display_name": self.display_name or "",
            "retry_count": str(self.retry_count),
        }

    @classmethod
    def from_fields(cls, fields: dict[Any, Any]) -> "DocumentIndexJob":
        data = {_decode(k): _decode(v) for k, v in fields.items()}
        return cls(
            job_id=data["job_id"],
            stored_path=data["stored_path"],
            original_name=data["original_name"],
            user_id=data["user_id"],
            topic_id=data["topic_id"],
            telegram_user_id=int(data["telegram_user_id"]),
            display_name=data.get("display_name") or None,
            retry_count=int(data.get("retry_count", "0") or 0),
        )


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _stream_name() -> str:
    return getattr(get_settings(), "media_jobs_stream", DEFAULT_STREAM)


def _group_name() -> str:
    return getattr(get_settings(), "media_jobs_group", DEFAULT_GROUP)


def _consumer_name() -> str:
    configured = getattr(get_settings(), "media_jobs_consumer", "")
    if configured:
        return configured
    return f"{socket.gethostname()}-{os.getpid()}"


def _block_ms() -> int:
    return int(getattr(get_settings(), "media_jobs_block_ms", DEFAULT_BLOCK_MS))


def _reclaim_idle_ms() -> int:
    return int(getattr(get_settings(), "media_jobs_reclaim_idle_ms", DEFAULT_RECLAIM_IDLE_MS))


def _redis_url() -> str:
    redis_url = get_settings().redis_url
    if not redis_url:
        raise RuntimeError("REDIS_URL is required for media document jobs")
    return redis_url


def _redis():
    return redis_from_url(_redis_url(), encoding="utf-8", decode_responses=True)


async def enqueue_document_index(job: DocumentIndexJob) -> str:
    redis = _redis()
    try:
        return await redis.xadd(_stream_name(), job.to_fields())
    finally:
        await redis.aclose()


async def ensure_group(redis) -> None:
    try:
        await redis.xgroup_create(_stream_name(), _group_name(), id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _run_document_index_job(job: DocumentIndexJob) -> None:
    from app.telegram.handlers import _index_document_job

    await _index_document_job(
        stored_path=Path(job.stored_path),
        original_name=job.original_name,
        user_id=UUID(job.user_id),
        topic_id=UUID(job.topic_id),
        telegram_user_id=job.telegram_user_id,
        display_name=job.display_name,
        job_id=job.job_id,
        retry_count=job.retry_count,
    )


async def _handle_stream_message(redis, message_id: str, fields: dict[Any, Any]) -> None:
    try:
        kind = _decode(fields.get("kind", ""))
        if kind != DOCUMENT_INDEX_KIND:
            logger.error("unknown_media_job", extra={"job_kind": kind, "message_id": message_id})
            return
        job = DocumentIndexJob.from_fields(fields)
        await _run_document_index_job(job)
        logger.info("media_job_ok", extra={"event": "media_job_ok", "job_id": job.job_id, "message_id": message_id})
    except Exception as exc:
        logger.exception("media_job_failed", extra={"event": "media_job_failed", "error": str(exc), "message_id": message_id})
    finally:
        await redis.xack(_stream_name(), _group_name(), message_id)


async def _claim_stale(redis, consumer: str) -> bool:
    claimed = await redis.xautoclaim(
        _stream_name(),
        _group_name(),
        consumer,
        min_idle_time=_reclaim_idle_ms(),
        start_id="0-0",
        count=10,
    )
    messages = claimed[1] if len(claimed) > 1 else []
    for message_id, fields in messages:
        await _handle_stream_message(redis, message_id, fields)
    return bool(messages)


async def worker_loop() -> None:
    redis = _redis()
    consumer = _consumer_name()
    try:
        await ensure_group(redis)
        logger.info("media_worker_started", extra={"stream": _stream_name(), "group": _group_name(), "consumer": consumer})
        while True:
            if await _claim_stale(redis, consumer):
                continue
            response = await redis.xreadgroup(
                _group_name(),
                consumer,
                streams={_stream_name(): ">"},
                count=1,
                block=_block_ms(),
            )
            for _, messages in response:
                for message_id, fields in messages:
                    await _handle_stream_message(redis, message_id, fields)
    finally:
        await redis.aclose()


def start_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(worker_loop())


async def stop_worker() -> None:
    global _worker_task
    if not _worker_task:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    _worker_task = None
