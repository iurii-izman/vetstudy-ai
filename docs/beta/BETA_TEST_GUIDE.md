# VetStudy AI Beta Test Guide

## Scope
Этот гайд актуален для beta-окна **1-2 недели** и покрывает Telegram-first сценарии, web API, безопасность, стабильность и качество ответов.

## Быстрый старт
1. Проверить `.env` и обязательные переменные (`TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, `USER_ID_HASH_SALT`, `WEB_OWNER_TELEGRAM_ID`, `WEB_OWNER_PASSWORD_HASH` или `WEB_OWNER_PASSWORD`, `WEB_OWNER_TOKEN`, `WEB_SESSION_SECRET`, ключ провайдера). Для beta можно временно использовать `ALLOWED_TELEGRAM_USERNAMES`, но после первого `/start` лучше заменить/дополнить стабильным Telegram ID.
2. Запустить сервис (`docker compose up --build` или локально API + polling/webhook).
3. Проверить `/health` и `/ready`.
4. В Telegram: `/start`, `/help`, затем `/bind_topic <slug>` или `/create_default_topics`.

Автопроверка перед beta:
```bash
python scripts/preflight_check.py --db --schema --provider
python scripts/quality_audit.py
```

## Команды бота
`/start`, `/help`, `/topics`, `/bind_topic <slug_or_name>`, `/create_default_topics`, `/new`, `/mode`, `/summary`, `/search`, `/save`, `/cards`, `/quiz`, `/review`, `/docs`, `/export`.

## E2E Test Plan

### 1) Новый пользователь
- Preconditions: новый Telegram user id не в БД.
- Steps: `/start` -> `/help` -> `/topics` -> `/bind_topic pharmacology` -> `/new`.
- Expected: создан user, topic привязан, активная сессия создана.

### 2) Вопрос по фармакологии
- Steps: вопрос по механизму действия/показаниям.
- Expected: осмысленный ответ по теме + inline actions.

### 3) Дозировка с недостаточными данными
- Steps: "Дай дозу ..." без вида/веса/пути.
- Expected: safety-gate блокирует прямую выдачу и просит уточнения.

### 4) Клинический случай
- Steps: отправить case-based вопрос с симптомами.
- Expected: структурированный разбор, дифференциалы, план next steps.

### 5) Поиск старого ответа
- Steps: `/search <query>`, выбрать результат кнопкой, `/cards search`.
- Expected: поиск по user-scoped memory, выбор и генерация карточек.

### 6) Карточки
- Steps: `/cards`, `/cards summary`, `/cards search`.
- Expected: создаются flashcards, доступны для `/review`.

### 7) Тест
- Steps: `/quiz` после последнего assistant-ответа.
- Expected: 7 вопросов с вариантами и объяснением.

### 8) Экспорт
- Steps: `/export anki`, `/export markdown`.
- Expected: отправка файлов CSV/MD, корректный контент.

### 9) Voice/Photo/PDF (если включено)
- Voice: отправить короткий voice -> транскрипт + ответ pipeline.
- Photo: отправить изображение -> OCR/Vision предупреждение + результат/ошибка.
- PDF/DOCX/TXT/MD: загрузить документ -> queued -> indexed (`/docs`).

### 10) Provider failure
- Preconditions: primary/fallback недоступны или неверные ключи.
- Steps: обычный вопрос.
- Expected: graceful fallback; при полном отказе user-safe сообщение.

### 11) Cost limit exceeded
- Preconditions: дневной/месячный лимит искусственно снижен.
- Steps: отправить запрос.
- Expected: отказ по лимиту, сервис не падает.

## Regression checklist (fixed before beta)
- Allowlist enforcement добавлен на все команды и media handlers.
- Callback isolation: нельзя выбрать чужой memory item.
- Flashcard review isolation: нельзя ревьюить чужую карточку.
- Topic uniqueness миграция: уникальность thread теперь scoped by `(chat_id, thread_id)`.

## Quality audit: 50 test questions
Перед реальной бетой прогнать `python scripts/quality_audit.py` на фактической production model:
- фармакология;
- клинические кейсы;
- дозировки и safety red flags;
- UX-команды и форматирование.

Фиксировать категории проблем:
- `слишком длинно`
- `неточно`
- `слишком осторожно`
- `не спросил уточнения`
- `плохо форматирует`

Важно: если включен `mock` provider (`LLM_PRIMARY_PROVIDER=mock`), точность LLM-контента невалидна для медоценки.

## Что НЕ считать назначением лечения
- Любые ответы VetStudy AI — учебная поддержка и помощь в структурировании мысли.
- Нельзя использовать как финальное клиническое назначение без очной оценки пациента и проверки официальной инструкции/формуляра.
- Экстренные и red-flag случаи должны эскалироваться в неотложную очную помощь.

## Как сообщать об ошибках
В баг-репорте указывать:
1. Дату/время и timezone.
2. Канал (Telegram thread id / web endpoint).
3. Шаги воспроизведения.
4. Ожидаемое/фактическое поведение.
5. Скриншот/текст ответа.
6. Если есть: `request_id`, `error_category`, provider/model.

Шаблон:
- Title: `[beta] <кратко>`
- Steps: `1..N`
- Expected:
- Actual:
- Evidence:

