from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models import ErrorEvent, FeedbackEvent, Message, ProductEvent, ReviewEvent, Session as ChatSession, Topic, User


class ProductAnalyticsService:
    _LEARNING_EVENT_PREFIXES = (
        "learning_",
        "checkpoint_",
        "remediation_",
        "recovery_",
        "progression_",
        "mastery_",
        "weak_skill_",
    )
    _LEARNING_EVENT_NAMES = {
        "overload_guard_triggered",
        "resume_requested",
        "resume_branch_selected",
        "resume_completed",
        "weekly_route_generated",
        "weekly_route_completed",
        "weekly_plan_opened",
        "weekly_recap_opened",
        "streak_milestone_reached",
    }

    def __init__(self, db: Session):
        self.db = db

    def _event_needs_experiment_tags(self, event_name: str) -> bool:
        if event_name in self._LEARNING_EVENT_NAMES:
            return True
        return event_name.startswith(self._LEARNING_EVENT_PREFIXES)

    def _resolve_experiment_tags(self, *, user_id) -> dict[str, str]:
        if not hasattr(self.db, "execute"):
            return {"experiment_id": "adaptive_mastery_loop_v1", "variant": "A"}
        user = self.db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        learning = dict(((user.settings or {}).get("learning") or {}) if user else {})
        exp = dict(learning.get("experiment") or {})
        return {
            "experiment_id": str(exp.get("experiment_id") or "adaptive_mastery_loop_v1"),
            "variant": str(exp.get("variant") or "A"),
        }

    def _enrich_properties(self, *, user_id, event_name: str, properties: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(properties or {})
        if self._event_needs_experiment_tags(event_name):
            tags = self._resolve_experiment_tags(user_id=user_id)
            payload.setdefault("experiment_id", tags["experiment_id"])
            payload.setdefault("variant", tags["variant"])
        return payload

    def track(self, *, user_id, event_name: str, topic_id=None, session_id=None, properties: dict[str, Any] | None = None) -> ProductEvent:
        payload = self._enrich_properties(user_id=user_id, event_name=event_name, properties=properties)
        if not hasattr(self.db, "add") or not hasattr(self.db, "commit"):
            return ProductEvent(user_id=user_id, topic_id=topic_id, session_id=session_id, event_name=event_name, properties=payload)
        row = ProductEvent(
            user_id=user_id,
            topic_id=topic_id,
            session_id=session_id,
            event_name=event_name,
            properties=payload,
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

    def journey_health(self, *, days: int = 30) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        rows = self.db.execute(
            select(ProductEvent.user_id, ProductEvent.event_name, ProductEvent.properties).where(ProductEvent.created_at >= since)
        ).all()
        drop_points: Counter[str] = Counter()
        dropped_users: set[Any] = set()
        recovered_users: set[Any] = set()
        first_week_users: set[Any] = set()
        first_week_completed: set[Any] = set()
        first_value_users: set[Any] = set()
        for user_id, event_name, props in rows:
            payload = props or {}
            if event_name == "activation_start":
                first_week_users.add(user_id)
            if event_name == "journey_drop_detected":
                reason = str(payload.get("reason", "unknown"))
                drop_points[reason] += 1
                dropped_users.add(user_id)
            if event_name in {"journey_recovered", "learning_relaunched"}:
                recovered_users.add(user_id)
            if event_name == "journey_state_changed" and str(payload.get("to")) == "habit":
                first_week_completed.add(user_id)
            if event_name == "learning_route_opened":
                first_value_users.add(user_id)
        recovery_rate = (len(recovered_users & dropped_users) / len(dropped_users)) if dropped_users else 0.0
        completion_rate = (len(first_week_completed) / len(first_week_users)) if first_week_users else 0.0
        first_value_rate = (len(first_value_users) / len(first_week_users)) if first_week_users else 0.0
        return {
            "drop_points": dict(drop_points),
            "dropped_users": len(dropped_users),
            "recovered_users": len(recovered_users & dropped_users),
            "recovery_rate": recovery_rate,
            "first_week_users": len(first_week_users),
            "first_week_completed": len(first_week_completed),
            "first_week_completion_rate": completion_rate,
            "first_value_10m_rate": first_value_rate,
        }

    def learning_outcomes(self, *, days: int = 30) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        review_rows = self.db.execute(
            select(ReviewEvent.score, ReviewEvent.created_at).where(ReviewEvent.created_at >= since).order_by(ReviewEvent.created_at.asc())
        ).all()
        scores = [int(score or 0) for score, _ in review_rows]
        if scores:
            head = scores[: max(1, len(scores) // 2)]
            tail = scores[len(head) :]
            learning_gain_proxy = (sum(tail) / max(1, len(tail))) - (sum(head) / max(1, len(head)))
        else:
            learning_gain_proxy = 0.0

        route_rows = self.db.execute(
            select(ProductEvent.properties).where(
                ProductEvent.event_name == "learning_route_opened",
                ProductEvent.created_at >= since,
            )
        ).all()
        fit_hits = 0
        fit_total = 0
        for row in route_rows:
            payload = row[0] or {}
            band = str(payload.get("difficulty_band", "medium"))
            due_count = int(payload.get("due_count", 0) or 0)
            reviewed = int(payload.get("reviewed_today", 0) or 0)
            fit_total += 1
            if (band == "easy" and due_count >= 3) or (band == "medium" and due_count in {1, 2, 3, 4}) or (band == "hard" and reviewed >= 1):
                fit_hits += 1
        difficulty_fit = (fit_hits / fit_total) if fit_total else 0.0

        adherence = self.learning_adherence(days=days)
        journey = self.journey_health(days=days)
        weak_drop_signals = int(journey.get("dropped_users", 0))
        skip_signals = int(adherence.get("learning_skipped_signals", 0))
        open_routes = int(adherence.get("learning_route_opened", 0))
        dropout_risk_score = min(1.0, round((skip_signals * 0.45 + weak_drop_signals * 0.7) / max(1, open_routes), 4))
        return {
            "learning_gain_proxy": round(float(learning_gain_proxy), 4),
            "difficulty_fit": round(float(difficulty_fit), 4),
            "dropout_risk_score": dropout_risk_score,
            "review_samples": len(scores),
            "route_samples": fit_total,
        }

    def learning_experiments(self, *, days: int = 30) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        rows = self.db.execute(
            select(ProductEvent.user_id, ProductEvent.event_name, ProductEvent.properties).where(ProductEvent.created_at >= since)
        ).all()
        by_event: Counter[str] = Counter()
        users_by_event: dict[str, set[Any]] = {}
        for user_id, event_name, props in rows:
            _ = props or {}
            by_event[event_name] += 1
            users_by_event.setdefault(event_name, set()).add(user_id)

        def rate(num: int, den: int) -> float:
            return (num / den) if den else 0.0

        cta_shown = by_event.get("learning_route_opened", 0)
        cta_clicked = by_event.get("learning_cta_clicked", 0)
        step_completed = by_event.get("learning_step_completed", 0)
        checkpoints_started = by_event.get("checkpoint_started", 0)
        checkpoints_completed = by_event.get("checkpoint_completed", 0)
        remediation_generated = by_event.get("remediation_plan_generated", 0)
        remediation_completed = by_event.get("remediation_plan_completed", 0)
        dropout_nudges = by_event.get("return_after_dropout_nudge", 0)
        comeback_success = by_event.get("learning_relaunched", 0)

        funnel = [
            {"step": "cta_shown", "count": int(cta_shown), "users": len(users_by_event.get("learning_route_opened", set()))},
            {"step": "clicked", "count": int(cta_clicked), "users": len(users_by_event.get("learning_cta_clicked", set()))},
            {"step": "step_completed", "count": int(step_completed), "users": len(users_by_event.get("learning_step_completed", set()))},
        ]
        checkpoints_table = [
            {"metric": "started", "count": int(checkpoints_started)},
            {"metric": "completed", "count": int(checkpoints_completed)},
            {"metric": "completion_rate", "count": round(rate(checkpoints_completed, checkpoints_started), 4)},
        ]
        remediation_table = [
            {"metric": "generated", "count": int(remediation_generated)},
            {"metric": "completed", "count": int(remediation_completed)},
            {"metric": "completion_rate", "count": round(rate(remediation_completed, remediation_generated), 4)},
        ]
        comeback_table = [
            {"metric": "dropout_nudges", "count": int(dropout_nudges)},
            {"metric": "relaunches", "count": int(comeback_success)},
            {"metric": "success_rate", "count": round(rate(comeback_success, dropout_nudges), 4)},
        ]

        return {
            "days": days,
            "kpis": {
                "checkpoint_completion_rate": round(rate(checkpoints_completed, checkpoints_started), 4),
                "remediation_completion_rate": round(rate(remediation_completed, remediation_generated), 4),
                "comeback_success_rate": round(rate(comeback_success, dropout_nudges), 4),
                "cta_step_completion_rate": round(rate(step_completed, cta_shown), 4),
            },
            "funnel": funnel,
            "checkpoint_table": checkpoints_table,
            "remediation_table": remediation_table,
            "comeback_table": comeback_table,
        }
