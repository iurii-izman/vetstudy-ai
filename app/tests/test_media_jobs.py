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
