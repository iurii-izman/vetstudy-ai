from datetime import UTC, datetime

from sqlalchemy import cast, func, literal, literal_column, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.types import Float

from app.db.models import (
    Document,
    DocumentChunk,
    ErrorEvent,
    Flashcard,
    FeedbackEvent,
    MemoryItem,
    Message,
    ModelCall,
    ReviewEvent,
    Session as ChatSession,
    SourceCitation,
    Subject,
    Topic,
    UsageCounter,
    User,
)


class UserRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, telegram_user_id: int, display_name: str | None, role: str = "user") -> User:
        row = self.db.execute(select(User).where(User.telegram_user_id == telegram_user_id)).scalar_one_or_none()
        if row:
            return row
        row = User(telegram_user_id=telegram_user_id, display_name=display_name, role=role)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def set_mode_preference(self, user: User, mode: str) -> User:
        settings = dict(user.settings or {})
        settings["mode"] = mode
        user.settings = settings
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_by_id(self, user_id) -> User | None:
        return self.db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()

    def list_all(self) -> list[User]:
        return list(self.db.execute(select(User).order_by(User.created_at.asc())).scalars().all())

    def complete_onboarding(self, user: User, *, language: str, specialization: str, subjects: list[str]) -> User:
        user.language = language
        user.specialization = specialization
        user.onboarding_subjects = subjects
        user.onboarding_completed = True
        self.db.commit()
        self.db.refresh(user)
        return user


class TopicRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, chat_id: int, thread_id: int | None, title: str = "Общее", user_id=None) -> Topic:
        q = select(Topic).where(Topic.telegram_chat_id == chat_id, Topic.telegram_thread_id == thread_id, Topic.user_id == user_id)
        row = self.db.execute(q).scalar_one_or_none()
        if row:
            return row
        row = Topic(telegram_chat_id=chat_id, telegram_thread_id=thread_id, title=title, user_id=user_id)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_by_chat_thread(self, chat_id: int, thread_id: int | None, user_id=None) -> Topic | None:
        q = select(Topic).where(Topic.telegram_chat_id == chat_id, Topic.telegram_thread_id == thread_id, Topic.user_id == user_id)
        return self.db.execute(q).scalar_one_or_none()

    def list_by_chat(self, chat_id: int, user_id=None) -> list[Topic]:
        q = select(Topic).where(Topic.telegram_chat_id == chat_id, Topic.user_id == user_id).order_by(Topic.created_at.asc())
        return list(self.db.execute(q).scalars().all())

    def get_many(self, topic_ids) -> list[Topic]:
        if not topic_ids:
            return []
        q = select(Topic).where(Topic.id.in_(list(topic_ids)))
        return list(self.db.execute(q).scalars().all())

    def bind_subject(self, *, chat_id: int, thread_id: int | None, subject: Subject, user_id=None) -> Topic:
        row = self.get_by_chat_thread(chat_id, thread_id, user_id=user_id)
        if row:
            row.subject_id = subject.id
            row.title = subject.title
            self.db.commit()
            self.db.refresh(row)
            return row
        row = Topic(
            subject_id=subject.id,
            telegram_chat_id=chat_id,
            telegram_thread_id=thread_id,
            title=subject.title,
            user_id=user_id,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row


class SessionRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_active(self, user_id, topic_id):
        q = select(ChatSession).where(ChatSession.user_id == user_id, ChatSession.topic_id == topic_id, ChatSession.is_active)
        return self.db.execute(q).scalar_one_or_none()

    def new_active(self, user_id, topic_id, mode: str = "practical") -> ChatSession:
        current = self.get_active(user_id, topic_id)
        if current:
            current.is_active = False
        row = ChatSession(user_id=user_id, topic_id=topic_id, mode=mode)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_or_create_active(self, user_id, topic_id, mode: str = "practical") -> ChatSession:
        row = self.get_active(user_id, topic_id)
        if row:
            return row
        return self.new_active(user_id=user_id, topic_id=topic_id, mode=mode)


class MessageRepo:
    def __init__(self, db: Session):
        self.db = db

    def add(self, session_id, role: str, content: str, telegram_message_id: int | None = None, metadata: dict | None = None) -> Message:
        row = Message(
            session_id=session_id,
            role=role,
            content=content,
            telegram_message_id=telegram_message_id,
            metadata_=metadata or {},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def last_assistant(self, session_id):
        q = (
            select(Message)
            .where(Message.session_id == session_id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        return self.db.execute(q).scalar_one_or_none()

    def recent_for_session(self, session_id, limit: int = 6) -> list[Message]:
        q = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows = list(self.db.execute(q).scalars().all())
        rows.reverse()
        return rows

    def count_for_session(self, session_id) -> int:
        q = select(Message).where(Message.session_id == session_id)
        return len(list(self.db.execute(q).scalars().all()))


class MemoryRepo:
    def __init__(self, db: Session):
        self.db = db

    def add(self, **kwargs) -> MemoryItem:
        row = MemoryItem(**kwargs)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def by_topic(self, topic_id, limit=5) -> list[MemoryItem]:
        q = select(MemoryItem).where(MemoryItem.topic_id == topic_id).order_by(MemoryItem.created_at.desc()).limit(limit)
        return list(self.db.execute(q).scalars().all())

    def add_many(self, rows: list[MemoryItem]) -> None:
        if not rows:
            return
        self.db.add_all(rows)
        self.db.commit()

    def search(self, topic_id, query: str, limit: int = 5) -> list[MemoryItem]:
        q = (
            select(MemoryItem)
            .where(MemoryItem.topic_id == topic_id, MemoryItem.content.ilike(f"%{query}%"))
            .order_by(MemoryItem.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(q).scalars().all())

    def by_user(self, user_id, limit: int = 200) -> list[MemoryItem]:
        q = (
            select(MemoryItem)
            .where(MemoryItem.user_id == user_id)
            .order_by(MemoryItem.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(q).scalars().all())

    def get(self, memory_id) -> MemoryItem | None:
        return self.db.execute(select(MemoryItem).where(MemoryItem.id == memory_id)).scalar_one_or_none()

    def latest_by_kind(self, *, topic_id, kind: str) -> MemoryItem | None:
        q = (
            select(MemoryItem)
            .where(MemoryItem.topic_id == topic_id, MemoryItem.kind == kind)
            .order_by(MemoryItem.created_at.desc())
            .limit(1)
        )
        return self.db.execute(q).scalar_one_or_none()


class DocumentRepo:
    def __init__(self, db: Session):
        self.db = db

    def create_or_get(self, *, user_id, topic_id, filename: str, size_bytes: int, job_id: str, metadata: dict | None = None) -> Document:
        row = self.db.execute(select(Document).where(Document.job_id == job_id)).scalar_one_or_none()
        if row:
            return row
        row = Document(
            user_id=user_id,
            topic_id=topic_id,
            filename=filename,
            size_bytes=size_bytes,
            job_id=job_id,
            status="queued",
            metadata_=metadata or {},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_by_job_id(self, job_id: str) -> Document | None:
        return self.db.execute(select(Document).where(Document.job_id == job_id)).scalar_one_or_none()

    def list_by_user(self, user_id, limit: int = 100) -> list[Document]:
        q = select(Document).where(Document.user_id == user_id).order_by(Document.created_at.desc()).limit(limit)
        return list(self.db.execute(q).scalars().all())

    def update_status(self, *, document: Document, status: str, chunks: int | None = None, error: str | None = None) -> Document:
        document.status = status
        metadata = dict(document.metadata_ or {})
        if chunks is not None:
            metadata["chunks"] = chunks
        if error:
            metadata["error"] = error
        document.metadata_ = metadata
        if status == "indexed":
            document.indexed_at = datetime.now(UTC)
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document


class DocumentChunkRepo:
    def __init__(self, db: Session):
        self.db = db

    def add_or_get(self, **kwargs) -> DocumentChunk:
        row = self.db.execute(
            select(DocumentChunk).where(
                DocumentChunk.document_id == kwargs["document_id"],
                DocumentChunk.chunk_hash == kwargs["chunk_hash"],
            )
        ).scalar_one_or_none()
        if row:
            return row
        row = DocumentChunk(**kwargs)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def add_many(self, rows: list[DocumentChunk]) -> None:
        if not rows:
            return
        self.db.add_all(rows)
        self.db.commit()

    def search_hybrid(self, *, user_id, query: str, query_tags: list[str], query_vec: list[float], current_topic_id=None, top_k: int = 5, cross_topic: bool = True):
        lexical = func.coalesce(func.length(DocumentChunk.content) - func.length(func.replace(func.lower(DocumentChunk.content), func.lower(query), "")), 0)
        lexical = cast(lexical, Float) / cast(func.nullif(func.length(query), 0), Float)
        lexical = func.coalesce(lexical, 0.0)

        topic_boost = literal(2.0) if current_topic_id is None else func.coalesce(cast((DocumentChunk.topic_id == current_topic_id), Float) * 2.0, 0.0)
        tag_score = literal(0.0)
        if query_tags and self.db.bind and self.db.bind.dialect.name == "postgresql":
            tag_score = cast(DocumentChunk.tags.op("&&")(query_tags), Float) * 1.25

        query_stmt = select(
            DocumentChunk,
            (lexical + tag_score + topic_boost).label("score"),
        ).where(DocumentChunk.user_id == user_id)
        if not cross_topic and current_topic_id is not None:
            query_stmt = query_stmt.where(DocumentChunk.topic_id == current_topic_id)

        if query_vec and self.db.bind and self.db.bind.dialect.name == "postgresql":
            vector_literal = "[" + ",".join(str(float(x)) for x in query_vec) + "]"
            vector_distance = DocumentChunk.embedding.op("<=>")(vector_literal)
            vector_score = (literal(1.0) - cast(vector_distance, Float)) * 2.5
            query_stmt = query_stmt.add_columns((lexical + tag_score + topic_boost + vector_score).label("score"))

        query_stmt = query_stmt.order_by(literal_column("score").desc(), DocumentChunk.created_at.desc()).limit(min(top_k, 20))
        rows = self.db.execute(query_stmt).all()
        return [(row[0], float(row[-1] or 0.0)) for row in rows]


class SourceCitationRepo:
    def __init__(self, db: Session):
        self.db = db

    def add(self, **kwargs) -> SourceCitation:
        row = SourceCitation(**kwargs)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row


class ReviewEventRepo:
    def __init__(self, db: Session):
        self.db = db

    def add(self, **kwargs) -> ReviewEvent:
        row = ReviewEvent(**kwargs)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row


class FeedbackEventRepo:
    def __init__(self, db: Session):
        self.db = db

    def add(self, **kwargs) -> FeedbackEvent:
        row = FeedbackEvent(**kwargs)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_recent(self, limit: int = 200, status: str | None = None) -> list[FeedbackEvent]:
        query = select(FeedbackEvent).order_by(FeedbackEvent.created_at.desc()).limit(limit)
        if status:
            query = query.where(FeedbackEvent.status == status)
        return list(self.db.execute(query).scalars().all())


class FlashcardRepo:
    def __init__(self, db: Session):
        self.db = db

    def add_many(self, cards: list[Flashcard]) -> None:
        self.db.add_all(cards)
        self.db.commit()

    def list_due(self, *, user_id, topic_id=None, now: datetime | None = None, limit: int = 20) -> list[Flashcard]:
        now = now or datetime.now(UTC)
        query = select(Flashcard).where(
            Flashcard.user_id == user_id,
            or_(Flashcard.due_at.is_(None), Flashcard.due_at <= now),
        )
        if topic_id is not None:
            query = query.where(Flashcard.topic_id == topic_id)
        query = query.order_by(Flashcard.created_at.asc()).limit(limit)
        return list(self.db.execute(query).scalars().all())

    def get(self, card_id) -> Flashcard | None:
        return self.db.execute(select(Flashcard).where(Flashcard.id == card_id)).scalar_one_or_none()

    def save(self, card: Flashcard) -> Flashcard:
        self.db.add(card)
        self.db.commit()
        self.db.refresh(card)
        return card

    def by_user(self, user_id, limit: int = 500) -> list[Flashcard]:
        q = select(Flashcard).where(Flashcard.user_id == user_id).order_by(Flashcard.created_at.asc()).limit(limit)
        return list(self.db.execute(q).scalars().all())


class SubjectRepo:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> list[Subject]:
        return list(self.db.execute(select(Subject).order_by(Subject.title.asc())).scalars().all())

    def get_by_slug_or_title(self, value: str) -> Subject | None:
        normalized = value.strip()
        if not normalized:
            return None
        q = select(Subject).where((Subject.slug == normalized) | (Subject.title.ilike(normalized)))
        row = self.db.execute(q).scalar_one_or_none()
        if row:
            return row
        fuzzy = select(Subject).where(Subject.title.ilike(f"%{normalized}%")).limit(1)
        return self.db.execute(fuzzy).scalar_one_or_none()

    def get_by_id(self, subject_id) -> Subject | None:
        return self.db.execute(select(Subject).where(Subject.id == subject_id)).scalar_one_or_none()

    def get_or_create(self, slug: str, title: str, system_prompt: str) -> Subject:
        row = self.db.execute(select(Subject).where(Subject.slug == slug)).scalar_one_or_none()
        if row:
            return row
        row = Subject(slug=slug, title=title, system_prompt=system_prompt)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row


class ModelCallRepo:
    def __init__(self, db: Session):
        self.db = db

    def add(self, **kwargs) -> ModelCall:
        row = ModelCall(**kwargs)
        self.db.add(row)
        self.db.commit()
        if hasattr(self.db, "refresh"):
            self.db.refresh(row)
        return row

    def usage_by_user(self, user_id):
        q = select(
            func.count(ModelCall.id),
            func.coalesce(func.sum(ModelCall.input_tokens), 0),
            func.coalesce(func.sum(ModelCall.output_tokens), 0),
            func.coalesce(func.sum(ModelCall.cost_usd), 0),
        ).where(ModelCall.user_id == user_id)
        return self.db.execute(q).one()

    def usage_all(self):
        q = select(
            func.count(ModelCall.id),
            func.coalesce(func.sum(ModelCall.input_tokens), 0),
            func.coalesce(func.sum(ModelCall.output_tokens), 0),
            func.coalesce(func.sum(ModelCall.cost_usd), 0),
        )
        return self.db.execute(q).one()


class UsageCounterRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, *, user_id, period_type: str, period_key: str) -> UsageCounter:
        row = self.db.execute(
            select(UsageCounter).where(
                UsageCounter.user_id == user_id,
                UsageCounter.period_type == period_type,
                UsageCounter.period_key == period_key,
            )
        ).scalar_one_or_none()
        if row:
            return row
        row = UsageCounter(user_id=user_id, period_type=period_type, period_key=period_key)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row


class ErrorEventRepo:
    def __init__(self, db: Session):
        self.db = db

    def add(self, *, user_id, scope: str, category: str, details: dict | None = None) -> ErrorEvent:
        row = ErrorEvent(user_id=user_id, scope=scope, category=category, details=details or {})
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_recent(self, limit: int = 100) -> list[ErrorEvent]:
        return list(self.db.execute(select(ErrorEvent).order_by(ErrorEvent.created_at.desc()).limit(limit)).scalars().all())
