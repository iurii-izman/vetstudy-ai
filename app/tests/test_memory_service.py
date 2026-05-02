from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.memory.service import MemoryService


class FakeEmbedder:
    async def embed(self, db, user_id, texts):
        text = texts[0].lower()
        if "панкреатит" in text:
            return [[0.9, 0.1, 0.0]]
        if "почки" in text:
            return [[0.1, 0.9, 0.0]]
        return [[0.6, 0.6, 0.0]]


class FakeMemoryRepo:
    def __init__(self, rows):
        self.rows = rows
        self.saved = []

    def add(self, **kwargs):
        self.saved.append(kwargs)
        return SimpleNamespace(id="m-new", **kwargs)

    def by_topic(self, topic_id, limit=5):
        items = [r for r in self.rows if r.topic_id == topic_id]
        return items[:limit]

    def by_user(self, user_id, limit=200):
        items = [r for r in self.rows if r.user_id == user_id]
        return items[:limit]


class FakeTopicRepo:
    def __init__(self, topics):
        self.topics = {t.id: t for t in topics}

    def get_many(self, topic_ids):
        return [self.topics[x] for x in topic_ids if x in self.topics]


class FakeChunkRepo:
    def __init__(self, rows):
        self.rows = rows

    def search_hybrid(self, **kwargs):
        user_id = kwargs["user_id"]
        filtered = [x for x in self.rows if x[0].user_id == user_id]
        return filtered[: kwargs.get("top_k", 5)]


def _item(idx, *, user_id, topic_id, content, tags=None, emb=None):
    return SimpleNamespace(
        id=f"m-{idx}",
        user_id=user_id,
        topic_id=topic_id,
        content=content,
        title="Ответ",
        tags=tags or [],
        embedding=emb,
        created_at=datetime(2026, 1, idx, tzinfo=timezone.utc),
    )


class VectorLike(list):
    def __bool__(self):
        raise ValueError("ambiguous truth value")


@pytest.mark.asyncio
async def test_retrieval_does_not_mix_users():
    rows = [
        _item(1, user_id="u1", topic_id="t1", content="Панкреатит у кошки", emb=[0.9, 0.1, 0.0]),
        _item(2, user_id="u2", topic_id="t1", content="Почечная недостаточность у собаки", emb=[0.1, 0.9, 0.0]),
    ]
    service = MemoryService(FakeMemoryRepo(rows), topic_repo=FakeTopicRepo([]), embedder=FakeEmbedder())
    results = await service.search(db=None, user_id="u1", query="панкреатит", current_topic_id="t1", top_k=5, cross_topic=True)
    assert len(results) == 1
    assert "Панкреатит" in results[0].snippet


@pytest.mark.asyncio
async def test_retrieval_prioritizes_current_topic():
    rows = [
        _item(1, user_id="u1", topic_id="current", content="Панкреатит кошек и инфузия", tags=["diseases", "procedures"], emb=VectorLike([0.9, 0.1, 0.0])),
        _item(2, user_id="u1", topic_id="other", content="Панкреатит и НПВС", tags=["diseases", "drugs"], emb=VectorLike([0.9, 0.1, 0.0])),
    ]
    service = MemoryService(FakeMemoryRepo(rows), topic_repo=FakeTopicRepo([]), embedder=FakeEmbedder())
    results = await service.search(db=None, user_id="u1", query="панкреатит", current_topic_id="current", top_k=2, cross_topic=True)
    assert results[0].topic_id == "current"


@pytest.mark.asyncio
async def test_cross_topic_links_work():
    topics = [
        SimpleNamespace(id="current", title="Текущая", telegram_thread_id=10),
        SimpleNamespace(id="rel1", title="Диагностика", telegram_thread_id=11),
        SimpleNamespace(id="rel2", title="Терапия", telegram_thread_id=12),
    ]
    rows = [
        _item(1, user_id="u1", topic_id="current", content="Панкреатит у кошки, риски", tags=["diseases", "risks"], emb=VectorLike([0.9, 0.1, 0.0])),
        _item(2, user_id="u1", topic_id="rel1", content="УЗИ и дифференциалы панкреатита", tags=["procedures", "diseases"], emb=VectorLike([0.8, 0.2, 0.0])),
        _item(3, user_id="u1", topic_id="rel2", content="НПВС и побочные эффекты", tags=["drugs", "risks"], emb=VectorLike([0.7, 0.3, 0.0])),
    ]
    service = MemoryService(FakeMemoryRepo(rows), topic_repo=FakeTopicRepo(topics), embedder=FakeEmbedder())
    related = await service.related_topics(db=None, user_id="u1", current_topic_id="current", top_k=2)
    assert len(related) == 2
    assert {x.id for x in related} == {"rel1", "rel2"}


@pytest.mark.asyncio
async def test_embedding_can_be_disabled():
    repo = FakeMemoryRepo([])
    service = MemoryService(repo, topic_repo=FakeTopicRepo([]), embedder=None)
    await service.ingest_assistant_answer(
        db=None,
        user_id="u1",
        topic_id="t1",
        source_message_id="msg-1",
        answer="Назначен мелоксикам кошке, оценены риски",
    )
    assert repo.saved[0]["embedding"] is None
    assert "drugs" in repo.saved[0]["tags"]


@pytest.mark.asyncio
async def test_document_chunk_search_included_and_user_isolated():
    chunk = SimpleNamespace(
        id="c1",
        user_id="u1",
        topic_id="t1",
        document_id="d1",
        content="Панкреатит подтверждён по УЗИ",
        metadata_={"document_title": "case.pdf"},
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    service = MemoryService(
        FakeMemoryRepo([]),
        topic_repo=FakeTopicRepo([SimpleNamespace(id="t1", title="Тема", telegram_thread_id=10)]),
        embedder=FakeEmbedder(),
        chunk_repo=FakeChunkRepo([(chunk, 3.0)]),
    )
    results = await service.search(db=None, user_id="u1", query="панкреатит", current_topic_id="t1", top_k=5, cross_topic=True)
    assert len(results) == 1
    assert results[0].document_id == "d1"
    assert results[0].chunk_id == "c1"
