from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import ProductEvent


@dataclass
class NudgeDecision:
    key: str
    text: str
    score: float


class ProactiveNudgeEngine:
    DAILY_CAP = 2
    WEEKLY_CAP_PER_KEY = 3

    def _count_recent(self, *, db, user_id, event_name: str, since: datetime) -> int:
        if not hasattr(db, "execute"):
            return 0
        rows = db.execute(
            select(ProductEvent.created_at).where(
                ProductEvent.user_id == user_id,
                ProductEvent.event_name == event_name,
                ProductEvent.created_at >= since,
            )
        ).all()
        return len(rows)

    def _can_send(self, *, db, user_id, key: str, now: datetime) -> bool:
        daily = self._count_recent(db=db, user_id=user_id, event_name="proactive_nudge_sent", since=now - timedelta(days=1))
        if daily >= self.DAILY_CAP:
            return False
        weekly_key = self._count_recent(db=db, user_id=user_id, event_name=f"proactive_nudge_sent:{key}", since=now - timedelta(days=7))
        return weekly_key < self.WEEKLY_CAP_PER_KEY

    def choose(self, *, db, user_id, dropout_days: int, overload: bool, high_risk_blocks: int, now: datetime | None = None) -> list[NudgeDecision]:
        now = now or datetime.now(UTC)
        candidates: list[NudgeDecision] = []
        if dropout_days >= 3:
            candidates.append(NudgeDecision("dropout", "Возврат после паузы: начни с /today light и закрой 2 карточки в /review.", min(1.0, 0.4 + dropout_days / 10)))
        if overload:
            candidates.append(NudgeDecision("overload", "Похоже на перегруз: оставь один фокус на сегодня и отложи остальное на завтра.", 0.75))
        if high_risk_blocks >= 3:
            candidates.append(NudgeDecision("high_risk_repeat", "Повторяются high-risk блоки: безопаснее перейти в /case basic и собрать недостающие данные по шаблону.", min(1.0, 0.5 + high_risk_blocks / 10)))

        ranked = sorted(candidates, key=lambda x: x.score, reverse=True)
        out: list[NudgeDecision] = []
        for item in ranked:
            if not self._can_send(db=db, user_id=user_id, key=item.key, now=now):
                continue
            out.append(item)
        return out[:2]
