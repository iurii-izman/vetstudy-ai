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

    def retrieval_quality(self, *, days: int = 30) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        search_rows = self.db.execute(
            select(ProductEvent.properties)
            .where(
                ProductEvent.event_name == "search_performed",
                ProductEvent.created_at >= since,
            )
        ).all()
        search_counts = [int((row[0] or {}).get("results", 0) or 0) for row in search_rows]
        search_total = len(search_counts)
        search_hits = sum(1 for count in search_counts if count > 0)
        search_zero = search_total - search_hits

        retrieval_rows = self.db.execute(
            select(ProductEvent.properties)
            .where(
                ProductEvent.event_name == "retrieval_context_built",
                ProductEvent.created_at >= since,
            )
        ).all()
        retrieval_props = [row[0] or {} for row in retrieval_rows]
        retrieved_counts = [int(item.get("results", 0) or 0) for item in retrieval_props]
        memory_hits = [int(item.get("memory_hits", 0) or 0) for item in retrieval_props]
        document_hits = [int(item.get("document_hits", 0) or 0) for item in retrieval_props]
        retrieval_total = len(retrieved_counts)
        retrieval_hits = sum(1 for count in retrieved_counts if count > 0)
        retrieval_zero = retrieval_total - retrieval_hits

        return {
            "search_total": search_total,
            "search_hit_rate": (search_hits / search_total) if search_total else 0.0,
            "search_empty_rate": (search_zero / search_total) if search_total else 0.0,
            "retrieval_total": retrieval_total,
            "retrieval_hit_rate": (retrieval_hits / retrieval_total) if retrieval_total else 0.0,
            "retrieval_empty_rate": (retrieval_zero / retrieval_total) if retrieval_total else 0.0,
            "avg_retrieved_chunks": (sum(retrieved_counts) / retrieval_total) if retrieval_total else 0.0,
            "avg_memory_hits": (sum(memory_hits) / retrieval_total) if retrieval_total else 0.0,
            "avg_document_hits": (sum(document_hits) / retrieval_total) if retrieval_total else 0.0,
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

    def learning_adherence(self, *, days: int = 30) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        tracked = self.db.execute(
            select(ProductEvent.event_name, ProductEvent.properties, ProductEvent.created_at).where(ProductEvent.created_at >= since)
        ).all()
        opened_today = 0
        completed_today = 0
        skipped_today = 0
        reopened_after_drop = 0
        milestone_hits = 0
        for event_name, props, _ in tracked:
            payload = props or {}
            if event_name == "learning_route_opened" and int(payload.get("due_count", 0) or 0) > 0 and int(payload.get("streak_days", 0) or 0) == 0:
                skipped_today += 1
                opened_today += 1
            elif event_name == "learning_route_opened":
                opened_today += 1
            elif event_name == "review_answered":
                completed_today += 1
            elif event_name == "learning_relaunched":
                reopened_after_drop += 1
            elif event_name == "streak_milestone_reached":
                milestone_hits += 1
        adherence_rate = (completed_today / opened_today) if opened_today else 0.0
        return {
            "learning_route_opened": opened_today,
            "learning_completed_actions": completed_today,
            "learning_skipped_signals": skipped_today,
            "reopened_after_dropout": reopened_after_drop,
            "streak_milestones": milestone_hits,
            "adherence_rate": adherence_rate,
        }

    def ux_conversion_summary(self, *, days: int = 30) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        rows = self.db.execute(
            select(ProductEvent.event_name, ProductEvent.properties).where(ProductEvent.created_at >= since)
        ).all()
        by_event: dict[str, int] = {}
        doc_cards = 0
        for event_name, props in rows:
            by_event[event_name] = by_event.get(event_name, 0) + 1
            payload = props or {}
            if event_name == "cards_created" and str(payload.get("source", "")).lower() == "document":
                doc_cards += 1
        voice_summary_offered = int(by_event.get("voice_summary_offered", 0))
        voice_summary_generated = int(by_event.get("voice_summary_generated", 0))
        document_nudges_viewed = int(by_event.get("document_learning_nudge_viewed", 0))
        return_after_dropout = int(by_event.get("return_after_dropout_nudge", 0))
        return {
            "document_to_cards": {"nudges_viewed": document_nudges_viewed, "cards_created_from_document": doc_cards},
            "voice_to_summary": {"offered": voice_summary_offered, "generated": voice_summary_generated},
            "return_after_dropout": {"nudges": return_after_dropout, "relaunches": int(by_event.get("learning_relaunched", 0))},
        }
