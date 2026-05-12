from __future__ import annotations
from dataclasses import dataclass

from sqlalchemy.exc import OperationalError, SQLAlchemyError


@dataclass(frozen=True)
class ErrorMapping:
    category: str
    user_message: str


class UserVisibleError(Exception):
    def __init__(self, message: str, *, category: str = "application_error"):
        super().__init__(message)
        self.message = message
        self.category = category


def map_pipeline_error(exc: Exception) -> ErrorMapping:
    if isinstance(exc, SQLAlchemyError):
        return ErrorMapping(
            category="db_error",
            user_message="Ошибка базы данных. Попробуйте чуть позже.",
        )
    if isinstance(exc, RuntimeError):
        return ErrorMapping(
            category="provider_error",
            user_message="LLM-провайдер временно недоступен. Проверьте ключи/лимиты и повторите позже.",
        )
    if "quota" in str(exc).lower() or "429" in str(exc):
        return ErrorMapping(
            category="quota_error",
            user_message="Лимит запросов или бюджета исчерпан. Попробуйте позже.",
        )
    return ErrorMapping(
        category="unexpected_error",
        user_message="Временная ошибка обработки. Попробуйте ещё раз.",
    )


def is_retryable_db_error(exc: Exception) -> bool:
    return isinstance(exc, OperationalError)
