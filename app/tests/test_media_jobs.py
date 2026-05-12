from types import SimpleNamespace
import uuid

import pytest

from app.media import jobs


class FakeRedis:
    def __init__(self):
        self.added = []
        self.acked = []
        self.closed = False

    async def xadd(self, stream, fields):
        self.added.append((stream, fields))
        return "1-0"

    async def xack(self, stream, group, message_id):
        self.acked.append((stream, group, message_id))

    async def aclose(self):
        self.closed = True

    async def xgroup_create(self, *_args, **_kwargs):
        return True

    async def xinfo_stream(self, _stream):
        return {"length": 3}

    async def xinfo_groups(self, _stream):
        return [{"name": jobs.DEFAULT_GROUP, "consumers": 1, "pending": 2, "lag": 1, "last-delivered-id": "1-0"}]

    async def xpending(self, _stream, _group):
        return {"pending": 2, "min": "1-0", "max": "2-0", "consumers": [{"name": "c1", "pending": 2}]}

    async def xpending_range(self, _stream, _group, _min, _max, _count):
        return [{"message_id": "1-0", "consumer": "c1", "time_since_delivered": 12000, "times_delivered": 1}]


@pytest.mark.asyncio
async def test_enqueue_document_index_writes_redis_stream(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(jobs, "get_settings", lambda: SimpleNamespace(redis_url="redis://localhost:6379/0"))
    monkeypatch.setattr(jobs, "redis_from_url", lambda *a, **k: redis)

    job = jobs.DocumentIndexJob(
        job_id=str(uuid.uuid4()),
        stored_path="/tmp/case.txt",
        original_name="case.txt",
        user_id=str(uuid.uuid4()),
        topic_id=str(uuid.uuid4()),
        telegram_user_id=7,
        display_name="U",
    )

    message_id = await jobs.enqueue_document_index(job)

    assert message_id == "1-0"
    assert redis.added == [(jobs.DEFAULT_STREAM, job.to_fields())]
    assert redis.closed is True


@pytest.mark.asyncio
async def test_handle_stream_message_acks_after_success(monkeypatch):
    redis = FakeRedis()
    handled = []
    monkeypatch.setattr(jobs, "_run_document_index_job", lambda job: _async_append(handled, job.job_id))

    await jobs._handle_stream_message(
        redis,
        "1-0",
        jobs.DocumentIndexJob(
            job_id="job-1",
            stored_path="/tmp/case.txt",
            original_name="case.txt",
            user_id=str(uuid.uuid4()),
            topic_id=str(uuid.uuid4()),
            telegram_user_id=7,
        ).to_fields(),
    )

    assert handled == ["job-1"]
    assert redis.acked == [(jobs.DEFAULT_STREAM, jobs.DEFAULT_GROUP, "1-0")]


@pytest.mark.asyncio
async def test_handle_stream_message_acks_after_failure(monkeypatch):
    redis = FakeRedis()

    async def _fail(_job):
        raise RuntimeError("index failed")

    monkeypatch.setattr(jobs, "_run_document_index_job", _fail)

    await jobs._handle_stream_message(
        redis,
        "1-1",
        jobs.DocumentIndexJob(
            job_id="job-2",
            stored_path="/tmp/bad.pdf",
            original_name="bad.pdf",
            user_id=str(uuid.uuid4()),
            topic_id=str(uuid.uuid4()),
            telegram_user_id=7,
        ).to_fields(),
    )

    assert redis.acked == [(jobs.DEFAULT_STREAM, jobs.DEFAULT_GROUP, "1-1")]


async def _async_append(target, value):
    target.append(value)


@pytest.mark.asyncio
async def test_worker_diagnostics_includes_pending_metrics(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(jobs, "get_settings", lambda: SimpleNamespace(redis_url="redis://localhost:6379/0"))
    monkeypatch.setattr(jobs, "redis_from_url", lambda *a, **k: redis)

    info = await jobs.worker_diagnostics()

    assert info["status"] == "ok"
    assert info["pending_count"] == 2
    assert info["oldest_pending_seconds"] == 12.0
