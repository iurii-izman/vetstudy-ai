from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import Message, ModelCall, Session as ChatSession


@dataclass
class QuotaDecision:
    allowed: bool
    message: str | None = None


class QuotaGuard:
    def __init__(self, settings):
        self.settings = settings

    def check_user_and_global(self, db, user) -> QuotaDecision:
        if not hasattr(db, "execute"):
            return QuotaDecision(True, None)
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

        day_messages = db.execute(
            select(func.count(Message.id))
            .join(ChatSession, ChatSession.id == Message.session_id)
            .where(
                ChatSession.user_id == user.id,
                Message.role == "user",
                Message.created_at >= day_start,
                Message.created_at < day_end,
            )
        ).scalar_one()
        if day_messages >= user.quota_messages_per_day:
            return QuotaDecision(False, "Дневной лимит сообщений исчерпан. Попробуйте завтра.")

        month_cost = db.execute(
            select(func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(
                ModelCall.user_id == user.id,
                ModelCall.created_at >= month_start,
                ModelCall.created_at < next_month,
            )
        ).scalar_one()
        if Decimal(month_cost) >= Decimal(user.quota_cost_per_month_usd):
            return QuotaDecision(False, "Месячный лимит AI-стоимости исчерпан. Попробуйте в следующем месяце.")

        global_day_cost = float(
            db.execute(select(func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(ModelCall.created_at >= day_start)).scalar_one()
            or 0
        )
        if global_day_cost >= float(self.settings.global_daily_cost_limit_usd):
            return QuotaDecision(False, "Сервис перегружен по дневному бюджету. Попробуйте позже.")

        global_month_cost = float(
            db.execute(select(func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(ModelCall.created_at >= month_start)).scalar_one()
            or 0
        )
        if global_month_cost >= float(self.settings.global_monthly_cost_limit_usd):
            return QuotaDecision(False, "Сервис достиг месячного бюджета. Попробуйте в следующем месяце.")

        return QuotaDecision(True, None)
