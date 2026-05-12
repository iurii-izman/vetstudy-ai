from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ProductEvent, User
from app.telegram.nudges import ProactiveNudgeEngine
from app.telegram.trust import compact_trust_trace


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def test_compact_trust_trace_has_manual_and_missing():
    text = compact_trust_trace(
        source="official",
        trust_level="high",
        verification_status="needs_manual_check",
        needs_manual_check=True,
        manual_check_reasons=["Need exact concentration."],
        missing_data=["Species?", "Weight?"],
    )
    assert "src=official" in text
    assert "manual=yes" in text
    assert "missing=Species?, Weight?" in text


def test_nudge_engine_applies_caps():
    db = _db()
    try:
        user = User(id=uuid4(), telegram_user_id=7, display_name="u")
        db.add(user)
        db.commit()
        now = datetime.now(UTC)
        for _ in range(2):
            db.add(ProductEvent(user_id=user.id, event_name="proactive_nudge_sent", properties={}, created_at=now - timedelta(hours=1)))
        db.commit()
        nudges = ProactiveNudgeEngine().choose(db=db, user_id=user.id, dropout_days=4, overload=True, high_risk_blocks=4, now=now)
        assert nudges == []
    finally:
        db.close()

