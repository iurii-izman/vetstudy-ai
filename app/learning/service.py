from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from sqlalchemy import func, select

from app.db.models import FeedbackEvent, Message, ProductEvent, ReviewEvent, Session as ChatSession, Topic

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
    mini_case: str
    drug_risk: str
    due_count: int
    review_cards: list[str]
    reflection_question: str
    used_fallback: bool
    weak_topics: list[str]
    zero_result_searches: int
    negative_feedback_count: int


@dataclass
class WeeklyRecap:
    cards_created: int
    cards_reviewed: int
    high_risk_queries: int
    questions_asked: int
    weak_topics: list[str]


class LearningService:
    CARD_SCHEMA_HINT = '{"cards":[{"front":"...","back":"...","card_type":"fact|cloze|case_next_step|risk_check|owner_explain","difficulty":"easy|medium|hard","needs_manual_check":false,"tags":["..."]}]}'
    QUIZ_SCHEMA_HINT = '{"quiz":[{"question":"...","options":["A) ...","B) ...","C) ...","D) ..."],"correct_answer":"A|B|C|D","explanation":"...","difficulty":"easy|medium|hard","tags":["..."]}]}'

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

    def build_daily_route(self, *, db, user_id, topic_id=None, now: datetime | None = None) -> DailyLearningRoute:
        now = now or datetime.now(UTC)
        since_7d = now - timedelta(days=7)
        due_cards = FlashcardRepo(db).list_due(user_id=user_id, topic_id=topic_id, now=now, limit=30)
        all_cards = FlashcardRepo(db).by_user(user_id, limit=200)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

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
        topic_title = None
        if topic_id is not None:
            topic_row = db.execute(select(Topic.title).where(Topic.id == topic_id)).one_or_none()
            topic_title = topic_row[0] if topic_row else None

        used_fallback = not bool(due_cards or all_cards)
        if used_fallback:
            return DailyLearningRoute(
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
            )

        review_cards = [card.front for card in due_cards[:3]]
        if len(review_cards) < 3:
            seen = set(review_cards)
            for card in all_cards:
                if card.front in seen:
                    continue
                review_cards.append(card.front)
                seen.add(card.front)
                if len(review_cards) >= 3:
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

        return DailyLearningRoute(
            mini_case=mini_case,
            drug_risk=drug_risk,
            due_count=len(due_cards),
            review_cards=review_cards[:3],
            reflection_question=reflection_question,
            used_fallback=False,
            weak_topics=weak_topics,
            zero_result_searches=zero_result_searches,
            negative_feedback_count=negative_feedback_count,
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
