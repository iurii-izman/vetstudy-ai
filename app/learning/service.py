from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
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


@dataclass
class RecoveryRouteDecision:
    intensity: str
    reason: str
    route: str
    comeback_days: int
    overload_signals: int
    success_signals: int


@dataclass
class CheckpointResult:
    checkpoint_score: int
    misconception_tags: list[str]
    recommended_next_step: str
    breakdown: str
    raw_items: list[dict]


@dataclass
class RemediationPlan:
    weak_skills: list[str]
    steps: list[dict]
    safety_framing: bool
    recommended_next_step: str


class LearningService:
    CARD_SCHEMA_HINT = '{"cards":[{"front":"...","back":"...","card_type":"fact|cloze|case_next_step|risk_check|owner_explain","difficulty":"easy|medium|hard","needs_manual_check":false,"tags":["..."]}]}'
    QUIZ_SCHEMA_HINT = '{"quiz":[{"question":"...","options":["A) ...","B) ...","C) ...","D) ..."],"correct_answer":"A|B|C|D","explanation":"...","difficulty":"easy|medium|hard","tags":["..."]}]}'
    DAY_MODES = {"light": {"minutes": 15, "review_n": 2}, "standard": {"minutes": 25, "review_n": 3}, "intensive": {"minutes": 40, "review_n": 5}}
    DIFFICULTY_LEVELS = ("easy", "medium", "hard")
    HIGH_RISK_TAGS = {"dosage_request", "toxicology", "drug_interaction", "emergency_or_red_flag", "clinical_case", "uncertain_source"}

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _normalize_mastery_score(self, value: float | int | None) -> int:
        score = self._safe_float(value, 0.0)
        return max(0, min(100, int(round(score))))

    def _normalize_mastery_confidence(self, value: float | int | None) -> float:
        conf = self._safe_float(value, 0.5)
        return round(max(0.0, min(1.0, conf)), 3)

    def _extract_review_mastery_delta(self, score: int | None) -> int:
        if score is None:
            return 0
        normalized = max(0, min(4, int(score)))
        return (normalized - 2) * 6

    def _extract_feedback_mastery_delta(self, feedback: str) -> int:
        kind = str(feedback or "").strip().lower()
        if kind == "up":
            return 2
        if kind in {"down", "error"}:
            return -4
        return 0

    def _apply_aging(self, settings: dict, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        topic_mastery = dict(settings.get("topic_mastery") or {})
        for key, row in topic_mastery.items():
            item = dict(row or {})
            updated_at = str(item.get("updated_at") or "")
            try:
                prev = datetime.fromisoformat(updated_at)
                days = max(0, (now - prev).days)
            except ValueError:
                days = 0
            conf = self._normalize_mastery_confidence(item.get("confidence", 0.5))
            if days > 0:
                decay = 0.97 ** min(days, 45)
                conf = 0.5 + (conf - 0.5) * decay
            item["confidence"] = self._normalize_mastery_confidence(conf)
            topic_mastery[key] = item
        settings["topic_mastery"] = topic_mastery

        raw_meta = dict(settings.get("weak_skills_meta") or {})
        if not raw_meta and settings.get("weak_skills"):
            raw_meta = {str(tag).strip().lower(): {"weight": 1.0, "last_seen": now.isoformat()} for tag in settings.get("weak_skills", [])}
        kept: dict[str, dict] = {}
        for tag, payload in raw_meta.items():
            t = str(tag).strip().lower()[:48]
            if not t:
                continue
            item = dict(payload or {})
            try:
                prev = datetime.fromisoformat(str(item.get("last_seen") or now.isoformat()))
                days = max(0, (now - prev).days)
            except ValueError:
                days = 0
            weight = max(0.0, min(1.5, self._safe_float(item.get("weight"), 1.0)))
            if days > 0:
                weight = weight * (0.94 ** min(days, 60))
            if weight >= 0.2:
                kept[t] = {"weight": round(weight, 4), "last_seen": now.isoformat()}
        settings["weak_skills_meta"] = kept
        ranked = sorted(kept.items(), key=lambda x: x[1]["weight"], reverse=True)
        settings["weak_skills"] = [tag for tag, info in ranked if info["weight"] >= 0.35][:60]
        return settings

    def update_mastery_for_topic(
        self,
        *,
        db,
        user_id,
        topic_id,
        topic_title: str | None,
        review_score: int | None = None,
        quiz_score_percent: int | None = None,
        feedback_type: str | None = None,
        detected_weak_skills: list[str] | None = None,
    ) -> tuple[dict, list[str]]:
        user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if user is None:
            return {}, []
        settings = self._apply_aging(dict(user.settings or {}))
        topic_key = str(topic_id)
        existing = dict((settings.get("topic_mastery") or {}).get(topic_key) or {})
        score = self._normalize_mastery_score(existing.get("score", 50))
        prev_conf = self._normalize_mastery_confidence(existing.get("confidence", 0.45))
        confidence = prev_conf
        delta = self._extract_review_mastery_delta(review_score) + self._extract_feedback_mastery_delta(feedback_type or "")
        if quiz_score_percent is not None:
            quiz_delta = int(round((max(0, min(100, int(quiz_score_percent))) - 55) / 8))
            delta += quiz_delta
            confidence = min(1.0, confidence + 0.05)
        if review_score is not None:
            confidence = min(1.0, confidence + 0.04)
        if feedback_type in {"down", "error"}:
            confidence = max(0.1, confidence - 0.06)
        confidence = self._normalize_mastery_confidence(prev_conf * 0.7 + confidence * 0.3)
        new_score = self._normalize_mastery_score(score + delta)
        updated = {
            "topic_id": topic_key,
            "topic_title": topic_title or existing.get("topic_title") or "topic",
            "score": new_score,
            "confidence": self._normalize_mastery_confidence(confidence),
            "updated_at": datetime.now(UTC).isoformat(),
            "last_delta": delta,
        }
        topic_mastery = dict(settings.get("topic_mastery") or {})
        topic_mastery[topic_key] = updated
        weak_skills_set = {str(x).strip().lower() for x in (settings.get("weak_skills") or []) if str(x).strip()}
        weak_meta = dict(settings.get("weak_skills_meta") or {})
        for skill in detected_weak_skills or []:
            tag = str(skill).strip().lower()
            if tag:
                normalized = tag[:48]
                weak_skills_set.add(normalized)
                current_weight = self._safe_float((weak_meta.get(normalized) or {}).get("weight"), 0.6)
                weak_meta[normalized] = {"weight": round(min(1.5, current_weight + 0.18), 4), "last_seen": datetime.now(UTC).isoformat()}
        if new_score <= 45 and topic_title:
            ttag = f"topic:{str(topic_title).strip().lower()[:40]}"
            weak_skills_set.add(ttag)
            current_weight = self._safe_float((weak_meta.get(ttag) or {}).get("weight"), 0.5)
            weak_meta[ttag] = {"weight": round(min(1.5, current_weight + 0.12), 4), "last_seen": datetime.now(UTC).isoformat()}
        settings["topic_mastery"] = topic_mastery
        for tag in weak_skills_set:
            if tag not in weak_meta:
                weak_meta[tag] = {"weight": 0.5, "last_seen": datetime.now(UTC).isoformat()}
        settings["weak_skills_meta"] = weak_meta
        settings = self._apply_aging(settings)
        user.settings = settings
        db.commit()
        return updated, list(settings["weak_skills"])

    def topic_mastery_snapshot(self, *, user_settings: dict | None, topic_id) -> dict:
        topic_mastery = dict((user_settings or {}).get("topic_mastery") or {})
        return dict(topic_mastery.get(str(topic_id)) or {})

    def detect_weak_skills_for_topic(
        self,
        *,
        db,
        user_id,
        topic_id,
        topic_title: str | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        now = now or datetime.now(UTC)
        since = now - timedelta(days=21)
        weak: set[str] = set()
        rows = db.execute(
            select(ReviewEvent.score)
            .where(
                ReviewEvent.user_id == user_id,
                ReviewEvent.topic_id == topic_id,
                ReviewEvent.created_at >= since,
            )
            .order_by(ReviewEvent.created_at.desc())
            .limit(20)
        ).all()
        low_scores = sum(1 for item in rows if self._safe_int(item[0], 2) <= 1)
        if low_scores >= 2:
            weak.add("low_review_retention")
        if topic_title:
            weak.add(f"topic:{topic_title.strip().lower()[:40]}")
        return sorted(weak)

    def select_recovery_route(
        self,
        *,
        due_count: int,
        relaunch_days: int,
        high_risk_block_count: int,
        negative_feedback_count: int,
        streak_days: int,
    ) -> RecoveryRouteDecision:
        overload_signals = int(high_risk_block_count >= 3) + int(negative_feedback_count >= 2) + int(due_count >= 7)
        success_signals = int(streak_days >= 5) + int(high_risk_block_count == 0) + int(negative_feedback_count == 0)
        if relaunch_days >= 3:
            return RecoveryRouteDecision("light", f"pause_{relaunch_days}_days", "comeback", relaunch_days, overload_signals, success_signals)
        if overload_signals >= 2:
            return RecoveryRouteDecision("light", "overload_guard", "overload_light", relaunch_days, overload_signals, success_signals)
        if success_signals >= 3 and streak_days >= 7:
            return RecoveryRouteDecision("intensive", "success_streak", "progression_up", relaunch_days, overload_signals, success_signals)
        return RecoveryRouteDecision("standard", "baseline", "standard", relaunch_days, overload_signals, success_signals)

    async def generate_checkpoint(self, *, llm_router, db, user_id, topic_title: str, context: str) -> list[dict]:
        prompt = (
            "Сгенерируй диагностический checkpoint JSON без markdown для vet study. "
            'Схема: {"checkpoint":[{"id":"q1","type":"mcq|reasoning","question":"...","options":["A) ...","B) ...","C) ...","D) ..."],"correct_answer":"A|B|C|D|short","ideal_answer":"...","rationale":"...","misconception_tag":"...","why_in_practice":"..."}]}. '
            "Ровно 5 вопросов: 3 mcq и 2 reasoning. Для reasoning correct_answer='short'. "
            "Избегай unsafe numeric shortcuts и не формируй назначение терапии как предписание."
            f"\nТема: {topic_title}\nКонтекст:\n{context[:3500]}"
        )
        raw = await llm_router.generate(db, user_id, prompt, purpose="summary")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        items: list[dict] = []
        for row in payload.get("checkpoint", []):
            qtype = str(row.get("type", "")).strip().lower()
            if qtype not in {"mcq", "reasoning"}:
                continue
            question = self._clip(row.get("question", ""), 12, 260)
            if not question:
                continue
            options = [self._clip(opt, 4, 150) for opt in (row.get("options") or [])][:4]
            if qtype == "mcq" and len([opt for opt in options if opt]) < 4:
                continue
            items.append(
                {
                    "id": self._clip(row.get("id", ""), 2, 12) or f"q{len(items)+1}",
                    "type": qtype,
                    "question": question,
                    "options": [opt for opt in options if opt],
                    "correct_answer": str(row.get("correct_answer", "short")).strip().upper(),
                    "ideal_answer": self._clip(row.get("ideal_answer", ""), 8, 260),
                    "rationale": self._clip(row.get("rationale", ""), 8, 300) or "Сверь логику с базовыми принципами triage и доказательности.",
                    "misconception_tag": self._clip(row.get("misconception_tag", ""), 3, 40) or "reasoning_gap",
                    "why_in_practice": self._clip(row.get("why_in_practice", ""), 8, 260) or "Важно для снижения клинических ошибок в реальной практике.",
                }
            )
            if len(items) >= 5:
                break
        return items

    def _keywords(self, text: str) -> set[str]:
        return {w for w in re.findall(r"[a-zA-Zа-яА-Я0-9_]{4,}", (text or "").lower()) if len(w) >= 4}

    def score_checkpoint_answers(self, *, items: list[dict], answers: dict[str, str]) -> CheckpointResult:
        if not items:
            return CheckpointResult(0, ["no_data"], "/fix_gaps", "Нет вопросов checkpoint.", [])
        lines: list[str] = []
        mis: list[str] = []
        total = 0
        max_score = max(1, len(items) * 20)
        for idx, item in enumerate(items, start=1):
            qid = str(item.get("id") or f"q{idx}")
            answer = (answers.get(qid) or "").strip()
            qtype = str(item.get("type") or "reasoning")
            correct = str(item.get("correct_answer") or "").strip().upper()
            ok = False
            if qtype == "mcq":
                user_letter = answer[:1].upper()
                ok = bool(user_letter and user_letter == correct)
            else:
                expected = item.get("ideal_answer") or item.get("rationale") or ""
                overlap = len(self._keywords(answer) & self._keywords(expected))
                ok = overlap >= 2
            if ok:
                total += 20
                lines.append(f"✅ Q{idx}: верно.")
            else:
                tag = str(item.get("misconception_tag") or "reasoning_gap").lower()
                mis.append(tag)
                lines.append(f"❌ Q{idx}: {item.get('rationale')}")
                lines.append(f"Почему важно в практике: {item.get('why_in_practice')}")
        score = int(round((total / max_score) * 100))
        next_step = "/fix_gaps" if score < 70 else "/today"
        return CheckpointResult(score, sorted(set(mis))[:8], next_step, "\n".join(lines), items)

    def evaluate_checkpoint(self, *, items: list[dict]) -> CheckpointResult:
        if not items:
            return CheckpointResult(0, ["no_data"], "/fix_gaps", "Checkpoint не сформирован: используй /fix_gaps и повтори попытку.", [])
        score = 0
        misconceptions: list[str] = []
        lines: list[str] = []
        for item in items:
            qtype = item.get("type", "reasoning")
            correct = str(item.get("correct_answer", "short")).upper()
            if qtype == "mcq":
                guessed = "A"
                is_ok = guessed == correct
            else:
                is_ok = False
            if is_ok:
                score += 20
                lines.append(f"✅ {item.get('question')}")
            else:
                tag = str(item.get("misconception_tag", "reasoning_gap")).strip().lower()
                misconceptions.append(tag)
                lines.append(f"❌ {item.get('question')} — {item.get('rationale')}")
                lines.append(f"Почему важно в практике: {item.get('why_in_practice')}")
        score = max(0, min(100, score))
        unique_mis = sorted(set(misconceptions))[:8]
        next_step = "/fix_gaps" if score < 70 else "/today"
        return CheckpointResult(score, unique_mis, next_step, "\n".join(lines), items)

    def build_remediation_plan(self, *, weak_skills: list[str], high_risk: bool) -> RemediationPlan:
        trimmed = [str(x).strip().lower()[:48] for x in weak_skills if str(x).strip()][:3] or ["low_review_retention"]
        case_focus = trimmed[0]
        steps = [
            {"kind": "mini_case", "title": f"Мини-кейс по пробелу: {case_focus}", "command": "/case basic"},
            {"kind": "card", "title": f"Карточка 1: ключевой триггер ошибки ({case_focus})", "command": "/cards"},
            {"kind": "card", "title": "Карточка 2: red flags и эскалация", "command": "/cards"},
            {"kind": "card", "title": "Карточка 3: безопасная коммуникация с владельцем", "command": "/cards"},
            {"kind": "micro_quiz", "title": "Микро-квиз из 3 вопросов", "command": "/quiz"},
        ]
        return RemediationPlan(trimmed, steps, bool(high_risk), "/today light")

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
        user_row = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        mastery_snapshot = self.topic_mastery_snapshot(user_settings=(user_row.settings if user_row else {}), topic_id=topic_id)
        mastery_score = self._safe_int(mastery_snapshot.get("score"), 55)
        if mastery_score < 45:
            difficulty_band = "easy"
            progression_mode = "recovery"
        elif mastery_score >= 80 and difficulty_band != "easy":
            difficulty_band = "hard"
            progression_mode = "progression_up"

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
                    planned_commands=["/today", "/case", "/review"],
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
