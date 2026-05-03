from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics import ProductAnalyticsService
from app.db.models import Base, ProductEvent, User


def test_product_analytics_summary_methods():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        user = User(telegram_user_id=7, display_name="u")
        db.add(user)
        db.commit()
        db.refresh(user)
        service = ProductAnalyticsService(db)
        service.track(user_id=user.id, event_name="activation_start")
        service.track(user_id=user.id, event_name="activation_first_question")
        db.add(ProductEvent(user_id=user.id, event_name="search_performed", properties={"results": 0, "topic_title": "T"}, created_at=datetime.now(UTC) - timedelta(days=1)))
        db.commit()

        funnel = service.activation_funnel(days=30)
        assert any(step["step"] == "activation_start" and step["users"] == 1 for step in funnel)
        gaps = service.content_gap_report(days=30)
        assert gaps["zero_results_total"] >= 1
        summary = service.behavior_summary(days=30)
        assert "events" in summary
    finally:
        db.close()
