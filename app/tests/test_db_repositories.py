from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Flashcard, Message
from datetime import UTC, datetime, timedelta

from app.db.repositories import FlashcardRepo, MessageRepo, SessionRepo, TopicRepo, UserRepo
from app.learning.service import LearningService


def _make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    return session


def test_user_get_or_create_idempotent():
    db = _make_db()
    try:
        repo = UserRepo(db)
        first = repo.get_or_create(telegram_user_id=12345, display_name="Alice")
        second = repo.get_or_create(telegram_user_id=12345, display_name="Bob")
        assert first.id == second.id
        assert second.display_name == "Alice"
    finally:
        db.close()


def test_topic_session_message_flow():
    db = _make_db()
    try:
        user = UserRepo(db).get_or_create(telegram_user_id=99, display_name="User")
        topic = TopicRepo(db).get_or_create(chat_id=1000, thread_id=10, title="Diagnostics")
        session = SessionRepo(db).get_or_create_active(user_id=user.id, topic_id=topic.id)
        same = SessionRepo(db).get_or_create_active(user_id=user.id, topic_id=topic.id)
        assert session.id == same.id

        message = MessageRepo(db).add(session_id=session.id, role="user", content="hello")
        assert message.role == "user"
        saved = db.execute(select(Message).where(Message.id == message.id)).scalar_one()
        assert saved.content == "hello"
    finally:
        db.close()


def test_flashcards_add_many():
    db = _make_db()
    try:
        user = UserRepo(db).get_or_create(telegram_user_id=111, display_name="User")
        topic = TopicRepo(db).get_or_create(chat_id=2000, thread_id=20, title="Surgery")
        cards = [
            Flashcard(user_id=user.id, topic_id=topic.id, front="Q1", back="A1", tags=["a"]),
            Flashcard(user_id=user.id, topic_id=topic.id, front="Q2", back="A2", tags=["b"]),
        ]
        FlashcardRepo(db).add_many(cards)
        count = len(db.execute(select(Flashcard)).scalars().all())
        assert count == 2
    finally:
        db.close()


def test_flashcards_review_due_flow():
    db = _make_db()
    try:
        user = UserRepo(db).get_or_create(telegram_user_id=222, display_name="User")
        topic = TopicRepo(db).get_or_create(chat_id=3000, thread_id=30, title="Therapy")
        card = Flashcard(
            user_id=user.id,
            topic_id=topic.id,
            front="Q",
            back="A",
            tags=["review"],
            ease=2.5,
            interval_days=1,
            due_at=datetime.now(UTC) - timedelta(days=1),
        )
        FlashcardRepo(db).add_many([card])
        due = FlashcardRepo(db).list_due(user_id=user.id, topic_id=topic.id)
        assert len(due) == 1
        updated, _ = LearningService().apply_review(card=due[0], action="known", now=datetime.now(UTC))
        FlashcardRepo(db).save(updated)
        due_after = FlashcardRepo(db).list_due(user_id=user.id, topic_id=topic.id)
        assert due_after == []
    finally:
        db.close()
