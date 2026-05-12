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
        service.track(user_id=user.id, event_name="onboarding_step_completed", properties={"step": "bind_topic"})
        service.track(user_id=user.id, event_name="weekly_recap_opened")
        service.track(user_id=user.id, event_name="learning_route_opened", properties={"due_count": 3, "streak_days": 0})
        service.track(user_id=user.id, event_name="review_answered", properties={"action": "good"})
        service.track(user_id=user.id, event_name="streak_milestone_reached", properties={"days": 3})
        service.track(user_id=user.id, event_name="document_learning_nudge_viewed", properties={"filename": "doc.txt"})
        service.track(user_id=user.id, event_name="cards_created", properties={"source": "document", "count": 3})
        service.track(user_id=user.id, event_name="voice_summary_offered", properties={})
        service.track(user_id=user.id, event_name="voice_summary_generated", properties={})
        service.track(user_id=user.id, event_name="return_after_dropout_nudge", properties={"dropout_days": 4})
        service.track(user_id=user.id, event_name="learning_relaunched", properties={"after_days": 4})
        db.add(ProductEvent(user_id=user.id, event_name="search_performed", properties={"results": 0, "topic_title": "T"}, created_at=datetime.now(UTC) - timedelta(days=1)))
        db.add(ProductEvent(user_id=user.id, event_name="retrieval_context_built", properties={"results": 0, "memory_hits": 0, "document_hits": 0}))
        db.add(ProductEvent(user_id=user.id, event_name="retrieval_context_built", properties={"results": 3, "memory_hits": 2, "document_hits": 1}))
        db.commit()

        funnel = service.activation_funnel(days=30)
        assert any(step["step"] == "activation_start" and step["users"] == 1 for step in funnel)
        gaps = service.content_gap_report(days=30)
        assert gaps["zero_results_total"] >= 1
        retrieval = service.retrieval_quality(days=30)
        assert retrieval["retrieval_total"] == 2
        assert retrieval["retrieval_hit_rate"] == 0.5
        assert retrieval["avg_retrieved_chunks"] == 1.5
        summary = service.behavior_summary(days=30)
        adherence = service.learning_adherence(days=30)
        conversions = service.ux_conversion_summary(days=30)
        assert "events" in summary
        assert summary["events"].get("onboarding_step_completed", 0) == 1
        assert summary["events"].get("weekly_recap_opened", 0) == 1
        assert adherence["learning_route_opened"] == 1
        assert adherence["learning_completed_actions"] == 1
        assert adherence["streak_milestones"] == 1
        assert conversions["document_to_cards"]["cards_created_from_document"] == 1
        assert conversions["voice_to_summary"]["generated"] == 1
        assert conversions["return_after_dropout"]["nudges"] == 1
    finally:
        db.close()
