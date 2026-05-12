from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ErrorEvent, Message, Session, Topic, User
from sqlalchemy import select
from scripts import safety_drift_monitor


def test_safety_drift_monitor_writes_alert(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = SessionLocal()
    user = User(id=uuid4(), telegram_user_id=10, display_name="u")
    topic = Topic(id=uuid4(), title="t", telegram_chat_id=1, telegram_thread_id=1, user_id=user.id)
    sess = Session(id=uuid4(), user_id=user.id, topic_id=topic.id, mode="practical")
    db.add_all([user, topic, sess])
    db.commit()
    db.add(Message(session_id=sess.id, role="user", content="Дай дозу мг/кг сейчас", created_at=datetime.now(UTC)))
    db.add(Message(session_id=sess.id, role="user", content="Собака съела шоколад, что дать", created_at=datetime.now(UTC)))
    db.commit()
    db.close()

    monkeypatch.setattr(safety_drift_monitor, "new_session", SessionLocal)
    code = safety_drift_monitor.run(lookback_hours=24, limit=50, min_hits=1)
    assert code == 0
    verify = SessionLocal()
    try:
        rows = verify.execute(select(ErrorEvent)).scalars().all()
        assert rows
    finally:
        verify.close()
