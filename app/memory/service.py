from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re
from typing import Any

from app.db.models import MemoryItem, Topic
from app.db.repositories import DocumentChunkRepo, MemoryRepo, TopicRepo


@dataclass
class SearchResult:
    memory_id: str | None
    document_id: str | None
    chunk_id: str | None
    source_title: str | None
    topic_id: str | None
    topic_title: str
    topic_thread_id: int | None
    created_at: datetime
    snippet: str


class MemoryService:
    def __init__(self, memory_repo: MemoryRepo, *, topic_repo: TopicRepo | None = None, embedder: Any | None = None, chunk_repo: DocumentChunkRepo | None = None):
        self.memory_repo = memory_repo
        self.topic_repo = topic_repo
        self.embedder = embedder
        self.chunk_repo = chunk_repo
        self.tag_taxonomy = {
            "drugs": ["мелоксикам", "карпрофен", "нпвс", "антибиотик", "цеф", "амокси", "предниз", "кетамин"],
            "species": ["кошка", "кот", "собака", "щенок", "кролик", "лошад", "крупный рогатый", "коров"],
            "diseases": ["панкреат", "гастрит", "перитонит", "сепсис", "анем", "гепат", "почечн", "эндокрин"],
            "procedures": ["узи", "рентген", "лапаротом", "хирург", "катетер", "инфуз", "анестез"],
            "risks": ["риск", "осложн", "противопоказ", "токсич", "побоч", "дегидрат"],
            "exam_practice": ["экзам", "тест", "кейс", "практик", "протокол", "дифференциал"],
        }

    def retrieve_for_topic(self, topic_id, limit: int = 5) -> list[str]:
        rows = self.memory_repo.by_topic(topic_id=topic_id, limit=limit)
        return [row.content for row in rows]

    async def ingest_assistant_answer(
        self,
        *,
        db,
        user_id,
        topic_id,
        source_message_id,
        answer: str,
        title: str = "Ответ",
        kind: str = "answer",
    ) -> MemoryItem:
        tags = self.extract_tags(answer)
        embedding = None
        if self.embedder is not None:
            try:
                vectors = await self.embedder.embed(db, user_id, [answer])
                if vectors:
                    embedding = vectors[0]
            except Exception:
                embedding = None
        return self.memory_repo.add(
            user_id=user_id,
            topic_id=topic_id,
            source_message_id=source_message_id,
            kind=kind,
            title=title,
            content=answer,
            tags=tags,
            embedding=embedding,
        )

    async def search(
        self,
        *,
        db,
        user_id,
        query: str,
        current_topic_id=None,
        top_k: int = 5,
        cross_topic: bool = True,
    ) -> list[SearchResult]:
        top_k = min(max(top_k, 1), 20)
        all_rows = self.memory_repo.by_user(user_id=user_id, limit=300)
        query_vec: list[float] = []
        query_tags = self.extract_tags(query)
        if self.embedder is not None:
            try:
                vectors = await self.embedder.embed(db, user_id, [query])
                if vectors:
                    query_vec = self._vector_values(vectors[0])
            except Exception:
                query_vec = []

        filtered = [r for r in all_rows if cross_topic or r.topic_id == current_topic_id]
        scored: list[tuple[float, MemoryItem]] = []
        for row in filtered:
            score = self._lexical_score(query, row.content)
            score += self._tag_score(query_tags, row.tags or [])
            row_vec = self._vector_values(row.embedding)
            if query_vec and row_vec:
                score += 2.5 * self._cosine_similarity(query_vec, row_vec)
            if current_topic_id and row.topic_id == current_topic_id:
                score += 2.0
            scored.append((score, row))
        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        selected = [row for _, row in scored[:top_k]]
        topic_map = self._topic_map(selected)
        results = [
            SearchResult(
                memory_id=str(item.id),
                document_id=None,
                chunk_id=None,
                source_title=item.title,
                topic_id=str(item.topic_id) if item.topic_id else None,
                topic_title=topic_map.get(item.topic_id).title if topic_map.get(item.topic_id) else "Unknown topic",
                topic_thread_id=topic_map.get(item.topic_id).telegram_thread_id if topic_map.get(item.topic_id) else None,
                created_at=item.created_at,
                snippet=self._snippet(item.content, query),
            )
            for item in selected
        ]
        if self.chunk_repo:
            chunk_rows = self.chunk_repo.search_hybrid(
                user_id=user_id,
                query=query,
                query_tags=query_tags,
                query_vec=query_vec,
                current_topic_id=current_topic_id,
                top_k=top_k,
                cross_topic=cross_topic,
            )
            chunk_topic_map = self._topic_map([x[0] for x in chunk_rows])
            for chunk, _score in chunk_rows:
                topic = chunk_topic_map.get(chunk.topic_id)
                results.append(
                    SearchResult(
                        memory_id=None,
                        document_id=str(chunk.document_id),
                        chunk_id=str(chunk.id),
                        source_title=(chunk.metadata_ or {}).get("document_title"),
                        topic_id=str(chunk.topic_id) if chunk.topic_id else None,
                        topic_title=topic.title if topic else "Unknown topic",
                        topic_thread_id=topic.telegram_thread_id if topic else None,
                        created_at=chunk.created_at,
                        snippet=self._snippet(chunk.content, query),
                    )
                )
            results.sort(key=lambda x: x.created_at, reverse=True)
            results = results[:top_k]
        return results

    async def related_topics(self, *, db, user_id, current_topic_id, top_k: int = 3) -> list[Topic]:
        all_rows = self.memory_repo.by_user(user_id=user_id, limit=400)
        current_rows = [x for x in all_rows if x.topic_id == current_topic_id]
        other_rows = [x for x in all_rows if x.topic_id != current_topic_id and x.topic_id]
        if not current_rows or not other_rows or not self.topic_repo:
            return []
        current_tags = set()
        for row in current_rows:
            current_tags.update(row.tags or [])
        topic_scores: dict[Any, float] = {}
        for row in other_rows:
            score = 0.0
            overlap = len(current_tags.intersection(set(row.tags or [])))
            score += overlap * 1.0
            row_vec = self._vector_values(row.embedding)
            current_vec = self._vector_values(current_rows[0].embedding)
            if row_vec and current_vec:
                score += self._cosine_similarity(current_vec, row_vec)
            if self._subject_graph_link(current_tags, set(row.tags or [])):
                score += 0.75
            topic_scores[row.topic_id] = max(topic_scores.get(row.topic_id, 0.0), score)
        ordered_ids = [k for k, _ in sorted(topic_scores.items(), key=lambda it: it[1], reverse=True)[:top_k]]
        topics = self.topic_repo.get_many(ordered_ids)
        by_id = {t.id: t for t in topics}
        return [by_id[x] for x in ordered_ids if x in by_id]

    async def summarize_topic(self, *, db, user_id, topic_id, mode: str = "topic") -> str:
        rows = self.memory_repo.by_user(user_id=user_id, limit=200)
        if mode == "session":
            scoped = [x for x in rows if x.topic_id == topic_id][:20]
        else:
            scoped = [x for x in rows if x.topic_id == topic_id][:40]
        if not scoped:
            return "Пока нет данных для summary."
        lines = [x.content.strip().replace("\n", " ")[:160] for x in scoped[:8]]
        return "Summary:\n" + "\n".join(f"- {line}" for line in lines)

    def extract_tags(self, text: str) -> list[str]:
        normalized = text.lower()
        found: list[str] = []
        for tag_group, patterns in self.tag_taxonomy.items():
            if any(p in normalized for p in patterns):
                found.append(tag_group)
        return found

    def _lexical_score(self, query: str, text: str) -> float:
        words = [w for w in re.split(r"\W+", query.lower()) if w]
        hay = text.lower()
        return float(sum(1 for w in words if w in hay))

    @staticmethod
    def _tag_score(query_tags: list[str], item_tags: list[str]) -> float:
        if not query_tags or not item_tags:
            return 0.0
        return float(len(set(query_tags).intersection(set(item_tags)))) * 1.25

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if len(a) == 0 or len(b) == 0 or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _vector_values(vector: Any) -> list[float]:
        if vector is None:
            return []
        try:
            return [float(x) for x in vector]
        except TypeError:
            return []

    @staticmethod
    def _snippet(content: str, query: str, size: int = 160) -> str:
        text = " ".join(content.strip().split())
        if len(text) <= size:
            return text
        q = query.strip().lower()
        idx = text.lower().find(q[:20]) if q else -1
        if idx < 0:
            return text[:size] + "..."
        start = max(0, idx - size // 3)
        end = min(len(text), start + size)
        return ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")

    def _topic_map(self, items: list[MemoryItem]) -> dict[Any, Topic]:
        if not self.topic_repo:
            return {}
        topic_ids = {item.topic_id for item in items if item.topic_id}
        topics = self.topic_repo.get_many(topic_ids)
        return {topic.id: topic for topic in topics}

    @staticmethod
    def _subject_graph_link(tags_a: set[str], tags_b: set[str]) -> bool:
        rules = [
            ({"drugs", "risks"}, {"diseases", "species"}),
            ({"procedures"}, {"risks", "diseases"}),
            ({"exam_practice"}, {"diseases", "procedures", "drugs"}),
        ]
        for left, right in rules:
            if (tags_a & left and tags_b & right) or (tags_b & left and tags_a & right):
                return True
        return False
