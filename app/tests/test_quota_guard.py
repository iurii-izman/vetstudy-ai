from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.models import Base, Message, ModelCall, Session, User
from app.quotas import QuotaGuard


def test_quota_guard_blocks_daily_messages():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    user = User(telegram_user_id=1, display_name="u", quota_messages_per_day=1)
    db.add(user)
    db.flush()
    sess = Session(user_id=user.id, topic_id=None, mode="practical")
    db.add(sess)
    db.flush()
    db.add(Message(session_id=sess.id, role="user", content="x", created_at=datetime.now(UTC)))
    db.commit()
    decision = QuotaGuard(Settings()).check_user_and_global(db, user)
    assert decision.allowed is False


def test_quota_guard_blocks_monthly_cost():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    user = User(telegram_user_id=2, display_name="u", quota_cost_per_month_usd=Decimal("0.1"))
    db.add(user)
    db.flush()
    db.add(ModelCall(user_id=user.id, provider="mock", model="m", purpose="answer", cost_usd=Decimal("1.0")))
    db.commit()
    decision = QuotaGuard(Settings()).check_user_and_global(db, user)
    assert decision.allowed is False
