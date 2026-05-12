from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from sqlalchemy import func, select

from app.db.models import FeedbackEvent, Message, ProductEvent, ReviewEvent, Session as ChatSession, Topic, User

from app.db.models import Flashcard
from app.db.repositories import FlashcardRepo


@dataclass
class QuizItem:
    question: str
    options: list[str]
    correct_answer: str
    explanation: str


@dataclass
class DailyLearningRoute:
    mode: str
    plan_minutes: int
    mini_case: str
    drug_risk: str
    due_count: int
    review_cards: list[str]
    reflection_question: str
    used_fallback: bool
    weak_topics: list[str]
    zero_result_searches: int
    negative_feedback_count: int
    high_risk_block_count: int
    skill_map: dict[str, dict[str, float | int | str]]
    difficulty_band: str
    progression_mode: str
    recovery_mode: bool
    why_personalization: str


@dataclass
class WeeklyRecap:
    cards_created: int
    cards_reviewed: int
    high_risk_queries: int
    questions_asked: int
    weak_topics: list[str]


@dataclass
class WeeklyPlanDay:
    day_index: int
    focus: str
    mode: str
    mini_case: str
    review_target: int
    quiz_target: int
    planned_commands: list[str]


@dataclass
class WeeklyLearningPlan:
    days: list[WeeklyPlanDay]
    weak_topics: list[str]
    overdue_count: int
    streak_days: int
    relaunch_days: int
    workload_budget: int
    total_density: int
    why_plan: str


class LearningService:
    CARD_SCHEMA_HINT = '{"cards":[{"front":"...","back":"...","card_type":"fact|cloze|case_next_step|risk_check|owner_explain","difficulty":"easy|medium|hard","needs_manual_check":false,"tags":["..."]}]}'
    QUIZ_SCHEMA_HINT = '{"quiz":[{"question":"...","options":["A) ...","B) ...","C) ...","D) ..."],"correct_answer":"A|B|C|D","explanation":"...","difficulty":"easy|medium|hard","tags":["..."]}]}'
    DAY_MODES = {"light": {"minutes": 15, "review_n": 2}, "standard": {"minutes": 25, "review_n": 3}, "intensive": {"minutes": 40, "review_n": 5}}
    DIFFICULTY_LEVELS = ("easy", "medium", "hard")

    def _difficulty_from_skill_map(self, skill_map: dict[str, dict[str, float | int | str]]) -> str:
        if not skill_map:
            return "medium"
        avg_conf = sum(float(item.get("confidence", 0.5) or 0.5) for item in skill_map.values()) / max(1, len(skill_map))
        avg_errors = sum(float(item.get("errors", 0) or 0) for item in skill_map.values()) / max(1, len(skill_map))
        if avg_conf < 0.4 or avg_errors >= 2:
            return "easy"
        if avg_conf > 0.72 and avg_errors <= 1:
            return "hard"
        return "medium"

    def _build_skill_map(
        self,
        *,
        weak_topics: list[str],
        zero_result_searches: int,
        negative_feedback_count: int,
        high_risk_block_count: int,
        recent_case_difficulty: list[str],
    ) -> dict[str, dict[str, float | int | str]]:
        topic_counts: dict[str, int] = {}
        for raw in weak_topics:
            base = raw.split(":", 1)[-1] if ":" in raw else raw
            name = base.strip().lower()
            if not name:
                continue
            topic_counts[name] = topic_counts.get(name, 0) + 1
        if not topic_counts:
            topic_counts["triage_basics"] = 1
        recent_level = (recent_case_difficulty[-1] if recent_case_difficulty else "basic").lower()
        out: dict[str, dict[str, float | int | str]] = {}
        for topic, errors in topic_counts.items():
            base_conf = 0.65 - min(0.35, float(errors) * 0.1)
            penalty = min(0.25, zero_result_searches * 0.03 + negative_feedback_count * 0.04 + high_risk_block_count * 0.02)
            confidence = round(max(0.05, min(0.95, base_conf - penalty)), 2)
            out[topic] = {
                "confidence": confidence,
                "errors": errors,
                "recent_case_level": recent_level,
                "updated_from": "review/case/feedback/search",
            }
        return out

    def _persist_skill_map(self, *, db, user_id, skill_map: dict[str, dict[str, float | int | str]]) -> None:
        if not hasattr(db, "add") or not hasattr(db, "commit"):
            return
        user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if user is None:
            return
        settings = dict(user.settings or {})
        learning = dict(settings.get("learning") or {})
        learning["skill_map"] = skill_map
        settings["learning"] = learning
        user.settings = settings
        db.commit()

    @staticmethod
    def _clip(text: str, min_len: int, max_len: int) -> str:
        value = " ".join((text or "").split()).strip()
        if len(value) < min_len:
            return ""
        return value[:max_len]

    def _normalize_card_payload(self, payload: dict, count: int, tags: list[str]) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for raw in payload.get("cards", []):
            front = self._clip(raw.get("front", ""), 12, 180)
            back = self._clip(raw.get("back", ""), 16, 400)
            if not front or not back:
                continue
            key = f"{front.lower()}::{back.lower()}"
            if key in seen:
                continue
            seen.add(key)
            normalized_tags = [str(t).strip().lower()[:32] for t in (raw.get("tags") or []) if str(t).strip()]
            out.append(
                {
                    "front": front,
                    "back": back,
                    "card_type": str(raw.get("card_type", "fact")),
                    "needs_manual_check": bool(raw.get("needs_manual_check", False)),
                    "difficulty": raw.get("difficulty", "medium") if raw.get("difficulty") in {"easy", "medium", "hard"} else "medium",
                    "tags": sorted(set([*tags, *normalized_tags]))[:12],
                }
            )
            if len(out) >= count:
                break
        return out

    def _normalize_quiz_payload(self, payload: dict, count: int) -> list[QuizItem]:
        out: list[QuizItem] = []
        for raw in payload.get("quiz", []):
            question = self._clip(raw.get("question", ""), 12, 220)
            explanation = self._clip(raw.get("explanation", ""), 10, 320)
            options = [self._clip(x, 4, 160) for x in (raw.get("options") or [])][:4]
            options = [x for x in options if x]
            answer = (raw.get("correct_answer") or "").strip().upper()
            if not question or len(options) < 4 or answer not in {"A", "B", "C", "D"}:
                continue
            out.append(QuizItem(question=question, options=options, correct_answer=answer, explanation=explanation or "Сверьтесь с конспектом."))
            if len(out) >= count:
                break
        return out

    async def generate_cards_structured(self, *, llm_router, db, user_id, text: str, count: int, tags: list[str], source_message_id: str | None = None) -> list[dict]:
        prompt = (
            "Сгенерируй учебные flashcards в JSON без markdown. "
            f"Схема: {self.CARD_SCHEMA_HINT}. "
            f"Количество: {count}. "
            "front=короткий вопрос, back=точный ответ. Без дублей. "
            "front 12-180 символов, back 16-400 символов, difficulty обязательный. "
            "Не создавать dosage cards с числовыми дозами без source/evidence; такие карточки помечать needs_manual_check: true."
            f"\nИсточник:\n{text[:4000]}"
        )
        raw = await llm_router.generate(db, user_id, prompt, purpose="summary")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        cards = self._normalize_card_payload(payload, count, tags)
        if source_message_id:
            for item in cards:
                item["source_message_id"] = source_message_id
        return cards

    async def generate_quiz_structured(self, *, llm_router, db, user_id, text: str, count: int) -> list[QuizItem]:
        prompt = (
            "Сгенерируй quiz в JSON без markdown. "
            f"Схема: {self.QUIZ_SCHEMA_HINT}. "
            f"Количество: {count}. Без дублей вопросов. "
            "В explanation подробно объясни, почему правильный вариант верен и чем опасны distractors (неверные варианты)."
            f"\nИсточник:\n{text[:4000]}"
        )
        raw = await llm_router.generate(db, user_id, prompt, purpose="summary")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        return self._normalize_quiz_payload(payload, count)

    def generate_cards(self, *, text: str, topic_id, source_message_id, tags: list[str], user_id, count: int = 5) -> list[Flashcard]:
        # Deterministic fallback for tests/offline mode; production /cards uses structured LLM generation.
        cards: list[Flashcard] = []
        normalized_text = (text or "").replace("!", ".").replace("?", ".")
        lines = [x for x in [self._clip(p, 16, 340) for p in normalized_text.split(".")] if x]
        if not lines:
            lines = ["Клинический факт по теме."]
        for idx, line in enumerate(lines[: max(3, min(10, count))], start=1):
            cards.append(
                Flashcard(
                    user_id=user_id,
                    topic_id=topic_id,
                    source_message_id=source_message_id,
                    front=f"{idx}. Что важно помнить по теме?",
                    back=line,
                    tags=sorted(set([*tags, "difficulty:medium"])),
                    due_at=datetime.now(UTC),
                    ease=2.5,
                    interval_days=1,
                )
            )
        return cards

    def generate_quiz(self, *, text: str, count: int = 5) -> list[QuizItem]:
        quiz: list[QuizItem] = []
        lines = [x for x in [self._clip(p, 18, 240) for p in (text or "").split("\n")] if x]
        if not lines:
            lines = ["Факт по теме"]
        for idx, line in enumerate(lines[: max(5, min(10, count))], start=1):
            correct = f"A) {line[:120]}"
            quiz.append(
                QuizItem(
                    question=f"{idx}. Какое утверждение верно?",
                    options=[correct, "B) Неверная интерпретация", "C) Противоположная тактика", "D) Данных недостаточно"],
                    correct_answer="A",
                    explanation=f"Опора на источник: {line}",
                )
            )
        return quiz

    def _normalize_day_mode(self, requested_mode: str | None) -> str:
        mode = str(requested_mode or "standard").strip().lower()
        if mode not in self.DAY_MODES:
            return "standard"
        return mode

    def _daily_activity_count(self, *, db, user_id, day_start: datetime, day_end: datetime) -> int:
        return int(
            db.execute(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == user_id,
                    ProductEvent.created_at >= day_start,
                    ProductEvent.created_at < day_end,
                    ProductEvent.event_name.in_(
                        [
                            "learning_route_opened",
                            "weekly_plan_opened",
                            "case_started",
                            "review_answered",
                            "quiz_opened",
                            "cards_created",
                        ]
                    ),
                )
            ).scalar_one()
            or 0
        )

    def compute_streak(self, *, db, user_id, now: datetime | None = None) -> tuple[int, int]:
        now = now or datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        streak = 0
        relaunch_days = 0
        gap_open = True
        for offset in range(0, 30):
            start = day_start - timedelta(days=offset)
            end = start + timedelta(days=1)
            activity = self._daily_activity_count(db=db, user_id=user_id, day_start=start, day_end=end)
            if offset == 0 and activity == 0:
                continue
            if activity > 0 and gap_open:
                streak += 1
                continue
            if activity == 0 and streak > 0:
                gap_open = False
                continue
            if activity > 0 and not gap_open:
                relaunch_days = offset
                break
        return streak, relaunch_days

    def build_daily_route(self, *, db, user_id, topic_id=None, now: datetime | None = None, mode: str = "standard") -> DailyLearningRoute:
        now = now or datetime.now(UTC)
        mode = self._normalize_day_mode(mode)
        mode_cfg = self.DAY_MODES[mode]
        since_7d = now - timedelta(days=7)
        due_cards = FlashcardRepo(db).list_due(user_id=user_id, topic_id=topic_id, now=now, limit=30)
        all_cards = FlashcardRepo(db).by_user(user_id, limit=200)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        overdue_count = int(sum(1 for card in due_cards if getattr(card, "due_at", None) and getattr(card, "due_at") < start_of_day))
        reviewed_today = int(
            db.execute(
                select(func.count(ReviewEvent.id)).where(
                    ReviewEvent.user_id == user_id,
                    ReviewEvent.created_at >= start_of_day,
                )
            ).scalar_one()
            or 0
        )
        cards_created_7d = int(
            db.execute(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == user_id,
                    ProductEvent.event_name == "cards_created",
                    ProductEvent.created_at >= (now - timedelta(days=7)),
                )
            ).scalar_one()
            or 0
        )
        search_rows = db.execute(
            select(ProductEvent.properties).where(
                ProductEvent.user_id == user_id,
                ProductEvent.event_name == "search_performed",
                ProductEvent.created_at >= since_7d,
            )
        ).all()
        zero_result_searches = sum(1 for row in search_rows if int((row[0] or {}).get("results", 0) or 0) == 0)
        negative_feedback_count = int(
            db.execute(
                select(func.count(FeedbackEvent.id)).where(
                    FeedbackEvent.user_id == user_id,
                    FeedbackEvent.feedback_type.in_(["down", "error"]),
                    FeedbackEvent.created_at >= since_7d,
                )
            ).scalar_one()
            or 0
        )
        high_risk_block_count = int(
            db.execute(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == user_id,
                    ProductEvent.event_name.in_(["high_risk_query", "safety_clarification_required"]),
                    ProductEvent.created_at >= since_7d,
                )
            ).scalar_one()
            or 0
        )
        weak_topic_rows = db.execute(
            select(Topic.title, func.count(ReviewEvent.id))
            .join(ReviewEvent, ReviewEvent.topic_id == Topic.id)
            .where(
                ReviewEvent.user_id == user_id,
                ReviewEvent.created_at >= since_7d,
                ReviewEvent.score.is_not(None),
                ReviewEvent.score <= 1,
            )
            .group_by(Topic.title)
            .order_by(func.count(ReviewEvent.id).desc())
            .limit(3)
        ).all()
        weak_topics = [str(title) for title, _ in weak_topic_rows if title]
        recent_error_rows = db.execute(
            select(ProductEvent.properties).where(
                ProductEvent.user_id == user_id,
                ProductEvent.event_name == "error_event",
                ProductEvent.created_at >= since_7d,
            )
        ).all()
        recent_errors = [str((row[0] or {}).get("kind", "unknown")) for row in recent_error_rows][-3:]
        case_diff_rows = db.execute(
            select(ProductEvent.properties).where(
                ProductEvent.user_id == user_id,
                ProductEvent.event_name == "case_feedback",
                ProductEvent.created_at >= since_7d,
            )
        ).all()
        recent_case_difficulty = [str((row[0] or {}).get("difficulty", "unknown")) for row in case_diff_rows][-5:]
        weak_topics_extended = weak_topics + [f"recent_error:{x}" for x in recent_errors] + [f"case_difficulty:{x}" for x in recent_case_difficulty]
        skill_map = self._build_skill_map(
            weak_topics=weak_topics_extended,
            zero_result_searches=zero_result_searches,
            negative_feedback_count=negative_feedback_count,
            high_risk_block_count=high_risk_block_count,
            recent_case_difficulty=recent_case_difficulty,
        )
        difficulty_band = self._difficulty_from_skill_map(skill_map)
        progression_mode = "controlled_progression"
        recovery_mode = bool(overdue_count >= 5 or (reviewed_today == 0 and len(due_cards) > 0))
        if recovery_mode:
            progression_mode = "recovery"
            mode = "light"
            mode_cfg = self.DAY_MODES[mode]
            difficulty_band = "easy"
        topic_title = None
        if topic_id is not None:
            topic_row = db.execute(select(Topic.title).where(Topic.id == topic_id)).one_or_none()
            topic_title = topic_row[0] if topic_row else None

        used_fallback = not bool(due_cards or all_cards)
        if used_fallback:
            return DailyLearningRoute(
                mode=mode,
                plan_minutes=mode_cfg["minutes"],
                mini_case="Кошка, 3 года: рвота и диарея 24ч, аппетит снижен. Назови triage-красные флаги, 3 дифференциала и минимум диагностики.",
                drug_risk="Препарат/риск: НПВС у кошек. Проверь вид, дегидратацию, почечные риски, сочетание со стероидами; при неполных данных — manual check.",
                due_count=0,
                review_cards=[
                    "Triage: когда рвота/диарея требует срочной эскалации?",
                    "Базовая диагностика: минимум при острой рвоте/диарее у собаки.",
                    "НПВС у кошек: ключевые противопоказания и мониторинг.",
                ],
                reflection_question="Какое одно уточнение в приеме сегодня сильнее всего снизило бы риск клинической ошибки?",
                used_fallback=True,
                weak_topics=weak_topics,
                zero_result_searches=zero_result_searches,
                negative_feedback_count=negative_feedback_count,
                high_risk_block_count=high_risk_block_count,
                skill_map=skill_map,
                difficulty_band=difficulty_band,
                progression_mode=progression_mode,
                recovery_mode=recovery_mode,
                why_personalization=f"fallback; difficulty={difficulty_band}; weak_topics={len(weak_topics)}; recovery={str(recovery_mode).lower()}",
            )

        review_target = int(mode_cfg["review_n"])
        if difficulty_band == "easy":
            review_target = max(2, review_target - 1)
        elif difficulty_band == "hard":
            review_target = min(6, review_target + 1)
        review_cards = [card.front for card in due_cards[:review_target]]
        if len(review_cards) < review_target:
            seen = set(review_cards)
            for card in all_cards:
                if card.front in seen:
                    continue
                review_cards.append(card.front)
                seen.add(card.front)
                if len(review_cards) >= review_target:
                    break

        seed_card = due_cards[0] if due_cards else all_cards[0]
        scope = topic_title or "текущей теме"
        mini_case = (
            f"Мини-кейс ({scope}): {seed_card.front}. "
            "Сформулируй 3 дифференциала и первый диагностический шаг."
        )

        full_text = " ".join([(seed_card.front or ""), (seed_card.back or "")]).lower()
        if "нпвс" in full_text or "meloxic" in full_text or "мелокс" in full_text:
            drug_risk = "Препарат/риск: НПВС. Проверь гидратацию, почечный статус, GI-риск, недавние стероиды и видовые ограничения."
        else:
            drug_risk = "Препарат/риск: антибиотики и нефротоксичность. Перед назначением проверь показания, почки, взаимодействия и план мониторинга."

        if reviewed_today == 0:
            reflection_question = "Что мешает закрыть первый цикл повторения сегодня, и какой самый маленький следующий шаг?"
        elif cards_created_7d == 0:
            reflection_question = "Какой пробел в теме стоит превратить в 1 новую карточку после сегодняшнего кейса?"
        else:
            reflection_question = "Какая типичная ошибка по этой теме у тебя еще возможна и как ты ее заранее поймаешь?"
        if negative_feedback_count > 0:
            reflection_question = "Какой риск в твоих последних ответах уже отмечен как слабое место и как ты его проверишь сегодня?"
        elif zero_result_searches > 0:
            reflection_question = "Как переформулировать вопрос так, чтобы поиск дал контекст вместо нулевого результата?"
        if overdue_count >= 5:
            reflection_question = "Как сократить backlog карточек: какие 2 карточки повторишь первыми, чтобы снять перегруз?"
        self._persist_skill_map(db=db, user_id=user_id, skill_map=skill_map)

        return DailyLearningRoute(
            mode=mode,
            plan_minutes=mode_cfg["minutes"],
            mini_case=mini_case,
            drug_risk=drug_risk,
            due_count=len(due_cards),
            review_cards=review_cards[:review_target],
            reflection_question=reflection_question,
            used_fallback=False,
            weak_topics=weak_topics_extended,
            zero_result_searches=zero_result_searches,
            negative_feedback_count=negative_feedback_count,
            high_risk_block_count=high_risk_block_count,
            skill_map=skill_map,
            difficulty_band=difficulty_band,
            progression_mode=progression_mode,
            recovery_mode=recovery_mode,
            why_personalization=(
                f"difficulty={difficulty_band}; progression={progression_mode}; "
                f"weak_topics={len(weak_topics_extended)}; overdue={overdue_count}; high_risk={high_risk_block_count}"
            ),
        )

    def build_week_plan(self, *, db, user_id, topic_id=None, now: datetime | None = None) -> WeeklyLearningPlan:
        now = now or datetime.now(UTC)
        route = self.build_daily_route(db=db, user_id=user_id, topic_id=topic_id, now=now, mode="standard")
        streak_days, relaunch_days = self.compute_streak(db=db, user_id=user_id, now=now)
        modes = ["light", "standard", "intensive", "standard", "light", "intensive", "standard"]
        workload_budget = 9 if route.recovery_mode else 13 if route.difficulty_band == "medium" else 15
        density = {"light": 1, "standard": 2, "intensive": 3}
        days: list[WeeklyPlanDay] = []
        used_budget = 0
        for day_idx in range(1, 8):
            mode = modes[day_idx - 1]
            if route.recovery_mode and day_idx <= 3:
                mode = "light"
            day_load = density.get(mode, 2)
            if used_budget + day_load > workload_budget:
                mode = "light"
                day_load = 1
            used_budget += day_load
            focus = route.weak_topics[(day_idx - 1) % max(1, len(route.weak_topics))] if route.weak_topics else "triage_basics"
            review_target = 2 if mode == "light" else 4 if mode == "standard" else 6
            quiz_target = 1 if mode == "light" else 2
            if route.difficulty_band == "easy":
                quiz_target = 1
            if route.due_count > 4:
                review_target = max(review_target, 4)
            days.append(
                WeeklyPlanDay(
                    day_index=day_idx,
                    focus=focus,
                    mode=mode,
                    mini_case=f"День {day_idx}: {route.mini_case}",
                    review_target=review_target,
                    quiz_target=quiz_target,
                    planned_commands=["/today", "/case", "/review", "/quiz"],
                )
            )
        return WeeklyLearningPlan(
            days=days,
            weak_topics=route.weak_topics,
            overdue_count=route.due_count,
            streak_days=streak_days,
            relaunch_days=relaunch_days,
            workload_budget=workload_budget,
            total_density=used_budget,
            why_plan=(
                f"prioritize weak topics ({len(route.weak_topics)}), overdue={route.due_count}, "
                f"high-risk={route.high_risk_block_count}, density={used_budget}/{workload_budget}"
            ),
        )

    def build_weekly_recap(self, *, db, user_id, now: datetime | None = None) -> WeeklyRecap:
        now = now or datetime.now(UTC)
        since = now - timedelta(days=7)
        cards_created = int(
            db.execute(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == user_id,
                    ProductEvent.event_name == "cards_created",
                    ProductEvent.created_at >= since,
                )
            ).scalar_one()
            or 0
        )
        cards_reviewed = int(
            db.execute(
                select(func.count(ReviewEvent.id)).where(
                    ReviewEvent.user_id == user_id,
                    ReviewEvent.created_at >= since,
                )
            ).scalar_one()
            or 0
        )
        high_risk_queries = int(
            db.execute(
                select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == user_id,
                    ProductEvent.event_name == "high_risk_query",
                    ProductEvent.created_at >= since,
                )
            ).scalar_one()
            or 0
        )
        questions_asked = int(
            db.execute(
                select(func.count(Message.id))
                .join(ChatSession, ChatSession.id == Message.session_id)
                .where(
                    ChatSession.user_id == user_id,
                    Message.role == "user",
                    Message.created_at >= since,
                )
            ).scalar_one()
            or 0
        )
        weak_rows = db.execute(
            select(Topic.title, func.count(ReviewEvent.id))
            .join(ReviewEvent, ReviewEvent.topic_id == Topic.id)
            .where(
                ReviewEvent.user_id == user_id,
                ReviewEvent.created_at >= since,
                ReviewEvent.score.is_not(None),
                ReviewEvent.score <= 1,
            )
            .group_by(Topic.title)
            .order_by(func.count(ReviewEvent.id).desc())
            .limit(3)
        ).all()
        return WeeklyRecap(
            cards_created=cards_created,
            cards_reviewed=cards_reviewed,
            high_risk_queries=high_risk_queries,
            questions_asked=questions_asked,
            weak_topics=[str(title) for title, _ in weak_rows if title],
        )

    def apply_review(self, *, card: Flashcard, action: str, now: datetime | None = None) -> tuple[Flashcard, int]:
        now = now or datetime.now(UTC)
        ease = float(card.ease or 2.5)
        interval = max(1, int(card.interval_days or 1))
        reps = int(getattr(card, "reps", 0) or 0)
        lapses = int(getattr(card, "lapses", 0) or 0)
        score_map = {"again": 0, "hard": 2, "good": 3, "easy": 4, "known": 4, "unknown": 1, "later": 2}
        score = score_map.get(action, 2)
        if score >= 4:
            ease = min(3.0, ease + 0.15)
            interval = max(2, int(round(interval * ease)))
            reps += 1
        elif score <= 1:
            ease = max(1.3, ease - 0.2)
            interval = 1
            lapses += 1
        else:
            ease = max(1.3, ease - 0.05) if action == "hard" else ease
            interval = max(1, interval // 2 if action in {"hard", "later"} else int(round(interval * 1.2)))
            reps += 1
        
        tags = list(card.tags or [])
        if lapses >= 2 and "leech" not in tags:
            tags.append("leech")
            card.tags = tags

        card.ease = ease
        card.interval_days = interval
        card.reps = reps
        card.lapses = lapses
        card.difficulty = round(max(1.0, min(10.0, 11 - ease * 3)), 2)
        card.stability_days = float(interval)
        card.last_reviewed_at = now
        card.due_at = now + timedelta(days=interval)
        return card, score

    def export_anki_csv(self, cards: list[Flashcard]) -> str:
        out = io.StringIO()
        writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(["front", "back", "tags", "source"])
        for card in cards:
            writer.writerow(
                [
                    card.front,
                    card.back,
                    " ".join(card.tags or []),
                    str(card.source_message_id or ""),
                ]
            )
        return out.getvalue()

    def export_markdown(self, *, topic_title: str, topic_summary: str, saved_notes: list[str], cards: list[Flashcard]) -> str:
        lines = [f"# {topic_title}", "", "## Topic Notes", topic_summary or "Нет summary.", "", "## Saved Notes"]
        if saved_notes:
            lines.extend([f"- {n}" for n in saved_notes])
        else:
            lines.append("- Нет сохранённых заметок.")
        lines.extend(["", "## Cards"])
        if cards:
            for card in cards:
                lines.append(f"- Q: {card.front}")
                lines.append(f"  A: {card.back}")
        else:
            lines.append("- Нет карточек.")
        return "\n".join(lines)
