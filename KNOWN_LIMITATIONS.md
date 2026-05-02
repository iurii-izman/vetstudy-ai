# Known Limitations (Beta)

1. LLM accuracy невалидна при `mock` provider.
- Если в окружении включен `LLM_PRIMARY_PROVIDER=mock`, ответы AI являются техническими заглушками.
- Медицинское качество контента нужно оценивать только на фактическом production provider.

2. Миграции проверены локально, но staging/prod все равно нужно валидировать отдельно.
- `alembic upgrade head` прошел на compose Postgres с pgvector.
- Перед публичной beta повторить миграции на целевой базе и проверить `/ready`.

3. Free-tier provider limits.
- Для beta включен быстрый Groq primary и OpenRouter free fallback.
- При пакетных проверках нужен pacing (`scripts/quality_audit.py --delay-s 6`), иначе free-tier может rate limit.

4. Safety gate rule-based.
- Возможны ложные срабатывания/пропуски на редких формулировках.
- Нужен мониторинг real-world промптов и тюнинг паттернов.
 - Post-generation validators добавлены, но это не заменяет экспертный медицинский review.

5. Telegram callbacks подписаны, но UX старых кнопок не переживает redeploy/TTL.
- Callback payload защищен HMAC и sliding TTL.
- Кнопки, отправленные до redeploy или старше TTL, будут отклонены как неизвестное действие.

6. OCR/Vision/Transcription зависят от внешних провайдеров.
- При отключенных провайдерах пользователю показывается graceful message.
- Качество распознавания фото/аудио нестабильно на шумных данных.

7. Export объемный для больших историй.
- При очень больших темах markdown/csv экспорт может стать тяжёлым без pagination/streaming.

8. Ограниченная операционная аналитика по unanswered сообщениям.
- Есть доступ к Telegram `getUpdates`, но нет полноценной SLA-очереди unanswered/timeout alerts.
 - Cost accounting теперь считает по usage/estimate, но точность зависит от актуальности прайс-таблицы моделей.

9. Web auth пока single-owner.
- Web API требует bearer-token и маппит владельца через `WEB_OWNER_TELEGRAM_ID`.
- В production обязательно сменить `WEB_OWNER_TOKEN` и `WEB_OWNER_PASSWORD`.

