from __future__ import annotations

import csv
import io
import re
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
    def generate_cards(self, *, text: str, topic_id, source_message_id, tags: list[str], user_id, count: int = 5) -> list[Flashcard]:
        lines = [x.strip() for x in re.split(r"[.\n!?]+", text) if len(x.strip()) > 20]
        if not lines:
            lines = [text.strip() or "Клинический факт"]
        cards: list[Flashcard] = []
        for idx, line in enumerate(lines[: max(3, min(10, count))], start=1):
            key = " ".join(line.split()[:8]).strip()
            cards.append(
                Flashcard(
                    user_id=user_id,
                    topic_id=topic_id,
                    source_message_id=source_message_id,
                    front=f"{idx}. Что важно помнить: {key}?",
                    back=line,
                    tags=tags,
                    due_at=datetime.now(UTC),
                    ease=2.5,
                    interval_days=1,
                )
            )
        return cards

    def generate_quiz(self, *, text: str, count: int = 5) -> list[QuizItem]:
        lines = [x.strip() for x in re.split(r"[.\n!?]+", text) if len(x.strip()) > 25]
        if not lines:
            lines = [text.strip() or "Факт по теме"]
        quiz: list[QuizItem] = []
        for idx, line in enumerate(lines[: max(5, min(10, count))], start=1):
            correct = f"A) {line}"
            quiz.append(
                QuizItem(
                    question=f"{idx}. Какое утверждение верно?",
                    options=[correct, "B) Неверная интерпретация", "C) Противоположная тактика", "D) Данных недостаточно"],
                    correct_answer="A",
                    explanation=f"Опора на источник: {line}",
                )
            )
        return quiz

    def apply_review(self, *, card: Flashcard, action: str, now: datetime | None = None) -> Flashcard:
        now = now or datetime.now(UTC)
        ease = float(card.ease or 2.5)
        interval = max(1, int(card.interval_days or 1))
        if action == "known":
            ease = min(3.0, ease + 0.15)
            interval = max(2, int(round(interval * ease)))
        elif action == "unknown":
            ease = max(1.3, ease - 0.2)
            interval = 1
        else:
            interval = max(1, interval // 2)
        card.ease = ease
        card.interval_days = interval
        card.due_at = now + timedelta(days=interval)
        return card

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
