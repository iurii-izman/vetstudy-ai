# Final Beta Audit

Дата аудита: 2026-05-03

## Итог

Проект соответствует MVP-1 из `docs/ai/VetStudyAI_FINAL_SPEC.md` по Telegram-first сценарию: forum topics, allowlist, LLM router/fallback, safety gate, память, поиск, summary, save, cards, quiz, mode, backup, Docker и README присутствуют.

После финальной доводки критичных локально исправимых блокеров для beta не осталось. Production-like `.env` подготовлен, provider smoke пройден, локальный Docker backend поднят и health/readiness проверены. Beta можно начинать после ручного Telegram smoke в группе.

## Что исправлено во время аудита

- Web API теперь требует bearer token для пользовательских endpoints, а не доверяет одному `X-User-Telegram-Id`.
- Web cabinet может работать после логина без ручной передачи `X-User-Telegram-Id`: owner берется из `WEB_OWNER_TELEGRAM_ID`, с fallback на первый `ALLOWED_TELEGRAM_USER_IDS`.
- Web topics теперь видят реальные Telegram topics, которые имеют `user_id=NULL`, но используются в сессиях/памяти/карточках пользователя.
- Inline-кнопки Telegram под ответом больше не заглушки: `Сохранить`, `Карточки`, `Тест`, `Связанные темы`, `Кратко`, `Глубже` выполняют реальные действия.
- `/help` теперь показывает `/review`, `/docs`, `/export`.
- Миграция `0003_multi_user` переводит старые роли в `user` перед добавлением check constraint.
- `.env.example`, README, free setup, beta guide и known limitations согласованы по web owner env.
- CI дополнен frontend test/build.
- `.gitignore` и `.dockerignore` исключают `web/node_modules`, `web/dist`, backups/logs.
- `.env` переведен в beta/prod posture: `APP_ENV=prod`, `DEBUG=false`, сгенерированы non-default `WEB_OWNER_PASSWORD`, `WEB_OWNER_TOKEN`, `USER_ID_HASH_SALT`, задан `WEB_OWNER_TELEGRAM_ID`.
- LLM provider order изменен на Groq primary + OpenRouter free fallback; старая OpenRouter model больше не имела endpoints.
- Добавлены `scripts/preflight_check.py` и `scripts/quality_audit.py`.
- Убран `datetime.utcnow()` из app и tests в пользу timezone-aware datetime.
- Выполнен full quality audit на 50 вопросов: 50/50 responses ok.
- Telegram inline callbacks подписаны HMAC с sliding TTL; invalid/expired payload отклоняется.
- Добавлена миграция `0005_flashcards_tags_drift_fix`, закрывающая schema drift старого volume по `flashcards.tags`.
- `scripts/preflight_check.py` теперь проверяет фактическую схему БД против SQLAlchemy-моделей (`--schema`).
- `alembic/env.py` умеет fallback `@db:` -> `@localhost:` для локальных миграций против compose DB.
- Фоновая индексация документов больше не зависит от detached SQLAlchemy objects; успех переводит документ в `indexed`, ошибки - в `failed` с записью `ErrorEvent`.
- Web session tokens теперь привязаны к Telegram ID из токена и не позволяют подменить пользователя через `X-User-Telegram-Id`.
- Root репозитория очищен: глубокие beta/spec/setup материалы перенесены в `docs/`, добавлены `AGENTS.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `.gitattributes`, GitHub templates, Dependabot, dependency review и CodeQL workflow.
- Добавлена drift-guard миграция `0009_product_events_drift_guard`, чтобы базы, ошибочно stamped на `0008` без `product_events`, восстанавливались через обычный `alembic upgrade head`.

## Проверки

Финальный publish pass (2026-05-03):

- `python -m ruff check .`: passed.
- `python -m pytest -q`: 103 passed.
- `npm test`: 3 passed.
- `npm run build`: passed.
- `npm audit --omit=dev`: 0 vulnerabilities.
- `docker compose config --quiet`: passed.
- `alembic upgrade head`: passed against compose Postgres via localhost override.
- `python scripts/preflight_check.py --db --schema --provider`: passed with one warning to prefer `WEB_OWNER_PASSWORD_HASH` over plain password.
- `python scripts/quality_audit.py --limit 10 --delay-s 1`: completed; generated artifacts are ignored and not part of the repo.

Historical beta audit checks:

- `python -m pytest`: 66 passed.
- `python -m ruff check . --exclude web/node_modules --exclude web/dist --exclude artifacts`: passed.
- `npm test`: 2 passed.
- `npm run build`: passed.
- `docker compose config --quiet`: passed.
- `alembic upgrade head`: passed локально против compose DB через localhost fallback.
- `python scripts/preflight_check.py --db --schema --provider`: passed на compose DB/schema/provider.
- `python scripts/quality_audit.py --delay-s 6`: 50 total, 50 ok, 0 failed.
- Docker runtime smoke: backend healthy, `/health`, `/ready`, `/api/web/subjects`, `/api/web/topics`, `/api/web/stats`, `/api/web/flashcards`, `/api/web/privacy/export` ok.
- Свежие backend logs после smoke: без `ERROR`, `Traceback`, `500`.

## Остаточные риски

- Content quality технически прогнан на 50 вопросах, но медицинская точность все равно требует ручного просмотра артефакта `artifacts/quality_audit/quality_audit_20260502_201239.md`.
- Safety gate rule-based: возможны false positive/false negative на редких формулировках.
- Document indexing jobs требуют Redis; если `REDIS_URL` не настроен, beta должна считаться неготовой к загрузке документов.
- Evidence mode не является полноценной проверкой источниками; это следующий продуктовый этап, не обязательный для MVP-1.
- Free-tier providers могут rate-limit при пакетном использовании; для audit нужен pacing.

## Доработки для AI-автопилота

### Prompt 1: raw upload deletion

```text
Ты backend engineer. Доведи privacy deletion для загруженных документов до production-like поведения.

Требования:
- при удалении topic/account удалять не только строки documents/document_chunks, но и raw files из `MEDIA_STORAGE_PATH`;
- операция должна быть идемпотентной: отсутствие файла не должно ломать удаление;
- добавить тесты на topic deletion и account deletion;
- обновить RUNBOOK/SECURITY, если меняется операционная процедура.
```

## Ручные действия пользователя

- Проверить, что `ALLOWED_TELEGRAM_USER_IDS` содержит именно нужных beta-пользователей.
- Создать/проверить приватную Telegram supergroup с Topics, добавить бота админом и выдать `can_manage_topics`.
- В Telegram вручную пройти beta smoke: `/start`, `/help`, `/create_default_topics` или `/bind_topic`, вопрос, inline buttons, `/search`, `/cards`, `/review`, `/export`.
- Просмотреть `artifacts/quality_audit/quality_audit_20260502_201239.md` и вручную отметить медицинские ошибки.
- Проверить restore backup на отдельной базе перед публичной beta.
- После 1-2 недель beta собрать реальные ошибки/вопросы и не масштабировать проект до исправления safety/privacy/cost проблем.

## ROI-20 status (2026-05-03)
1) implemented; 2) deferred-manual; 3) implemented; 4) implemented-basic; 5) implemented-basic; 6) implemented-basic; 7) implemented-basic; 8) implemented-basic; 9) implemented-basic; 10) implemented; 11) implemented-basic; 12) implemented-basic; 13) implemented-basic; 14) implemented-basic; 15) implemented-basic; 16) implemented; 17) deferred; 18) implemented-basic; 19) manual; 20) implemented.

Legend: implemented = done in code; implemented-basic = partial/iterative; deferred = explicit backlog; manual = runbook/human process.
