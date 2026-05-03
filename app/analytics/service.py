from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models import ErrorEvent, FeedbackEvent, Message, ProductEvent, ReviewEvent, Session as ChatSession, Topic


class ProductAnalyticsService:
    def __init__(self, db: Session):
        self.db = db

    def track(self, *, user_id, event_name: str, topic_id=None, session_id=None, properties: dict[str, Any] | None = None) -> ProductEvent:
        if not hasattr(self.db, "add") or not hasattr(self.db, "commit"):
            return ProductEvent(user_id=user_id, topic_id=topic_id, session_id=session_id, event_name=event_name, properties=properties or {})
        row = ProductEvent(
            user_id=user_id,
            topic_id=topic_id,
            session_id=session_id,
            event_name=event_name,
            properties=properties or {},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def activation_funnel(self, *, days: int = 30) -> list[dict[str, int]]:
        since = datetime.now(UTC) - timedelta(days=days)
        steps = [
            "activation_start",
            "activation_topic_bound",
            "activation_first_question",
            "activation_first_answer",
            "activation_first_cards",
            "activation_first_review",
        ]
        out: list[dict[str, int]] = []
        for step in steps:
            users_count = self.db.execute(
                select(func.count(func.distinct(ProductEvent.user_id))).where(
                    ProductEvent.event_name == step,
                    ProductEvent.created_at >= since,
                )
            ).scalar_one()
            out.append({"step": step, "users": int(users_count or 0)})
        return out

    def retention_lite(self, *, days: int = 30) -> dict[str, int]:
        since = datetime.now(UTC) - timedelta(days=days)
        rows = self.db.execute(
            select(ProductEvent.user_id, func.min(ProductEvent.created_at))
            .where(ProductEvent.created_at >= since)
            .group_by(ProductEvent.user_id)
        ).all()
        retained_1d = 0
        retained_7d = 0
        for user_id, first_ts in rows:
            next_day = first_ts + timedelta(days=1)
            week = first_ts + timedelta(days=7)
            day_hit = self.db.execute(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == user_id,
                    ProductEvent.created_at >= next_day,
                )
            ).scalar_one()
            week_hit = self.db.execute(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == user_id,
                    ProductEvent.created_at >= week,
                )
            ).scalar_one()
            retained_1d += 1 if int(day_hit or 0) > 0 else 0
            retained_7d += 1 if int(week_hit or 0) > 0 else 0
        return {"cohort_users": len(rows), "retained_1d": retained_1d, "retained_7d": retained_7d}

    def dau_like(self, *, days: int = 14) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(days=days)
        rows = self.db.execute(
            select(ProductEvent.created_at, ProductEvent.user_id).where(ProductEvent.created_at >= since)
        ).all()
        by_day: dict[date, set] = {}
        for ts, user_id in rows:
            key = ts.astimezone(UTC).date()
            by_day.setdefault(key, set()).add(user_id)
        return [{"day": key.isoformat(), "active_users": len(users)} for key, users in sorted(by_day.items())]

    def content_gap_report(self, *, days: int = 30) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        queries = self.db.execute(
            select(ProductEvent.properties)
            .where(
                ProductEvent.event_name == "search_performed",
                ProductEvent.created_at >= since,
            )
        ).all()
        zero = [row[0] for row in queries if int((row[0] or {}).get("results", 0)) == 0]
        by_topic = Counter((item or {}).get("topic_title", "unknown") for item in zero)
        return {
            "searches_total": len(queries),
            "zero_results_total": len(zero),
            "zero_results_by_topic": dict(by_topic),
        }

    def behavior_summary(self, *, days: int = 30) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        by_event_rows = self.db.execute(
            select(ProductEvent.event_name, func.count(ProductEvent.id))
            .where(ProductEvent.created_at >= since)
            .group_by(ProductEvent.event_name)
        ).all()
        by_event = {name: int(total) for name, total in by_event_rows}

        questions_by_subject = self.db.execute(
            select(Topic.title, func.count(Message.id))
            .join(ChatSession, ChatSession.topic_id == Topic.id)
            .join(Message, and_(Message.session_id == ChatSession.id, Message.role == "user"))
            .where(Message.created_at >= since)
            .group_by(Topic.title)
        ).all()

        cards_created = int(by_event.get("cards_created", 0))
        cards_reviewed = int(self.db.execute(select(func.count(ReviewEvent.id)).where(ReviewEvent.created_at >= since)).scalar_one() or 0)
        feedback_total = int(self.db.execute(select(func.count(FeedbackEvent.id)).where(FeedbackEvent.created_at >= since)).scalar_one() or 0)
        feedback_negative = int(
            self.db.execute(
                select(func.count(FeedbackEvent.id)).where(
                    FeedbackEvent.created_at >= since,
                    FeedbackEvent.feedback_type.in_(["down", "error"]),
                )
            ).scalar_one()
            or 0
        )
        error_total = int(self.db.execute(select(func.count(ErrorEvent.id)).where(ErrorEvent.created_at >= since)).scalar_one() or 0)
        unresolved_negative = int(
            self.db.execute(
                select(func.count(FeedbackEvent.id)).where(
                    FeedbackEvent.created_at >= since,
                    FeedbackEvent.feedback_type.in_(["down", "error"]),
                    FeedbackEvent.status.in_(["new", "in_review"]),
                )
            ).scalar_one()
            or 0
        )

        high_risk_queries = int(by_event.get("high_risk_query", 0))

        return {
            "events": by_event,
            "questions_by_topic": [{"topic": title, "questions": int(total)} for title, total in questions_by_subject],
            "cards_created": cards_created,
            "cards_reviewed": cards_reviewed,
            "feedback_total": feedback_total,
            "feedback_negative": feedback_negative,
            "feedback_error_rate": (feedback_negative / feedback_total) if feedback_total else 0.0,
            "errors_total": error_total,
            "unresolved_negative_feedback": unresolved_negative,
            "high_risk_query_count": high_risk_queries,
        }
