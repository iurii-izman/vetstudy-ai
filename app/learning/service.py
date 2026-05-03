from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.db.models import Flashcard


@dataclass
class QuizItem:
    question: str
    options: list[str]
    correct_answer: str
    explanation: str


class LearningService:
    CARD_SCHEMA_HINT = '{"cards":[{"front":"...","back":"...","difficulty":"easy|medium|hard","tags":["..."]}]}'
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
            "front 12-180 символов, back 16-400 символов, difficulty обязательный."
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
            f"Количество: {count}. Без дублей вопросов."
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
