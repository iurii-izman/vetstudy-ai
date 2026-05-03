# VetStudy AI Next Autopilot Blocks

Last updated: 2026-05-03.

Use these as current prompts for new Codex IDE sessions. They supersede the older MVP-building sequence in `docs/ai/VetStudyAI_AUTOPILOT_PROMPTS.md`, which is now mostly historical.

## Common Prefix

Paste this before every block:

```text
Работай в C:\Dev\pollychat. Соблюдай AGENTS.md. Сначала прочитай README.md, docs/ARCHITECTURE.md, docs/beta/RUNBOOK.md, docs/beta/CLOSED_BETA_DECISIONS.md, quality/dosage_policy_transnistria.md, docs/ai/AUTOPILOT_HANDOFF.md.

Не коммить .env, токены, raw uploads, backups, local DB data, generated audit artifacts, private Telegram IDs. Не убирай disclaimers, allowlist, quota guard, user isolation tests, dosage safety, evidence/manual-check behavior.

Делай маленький auditable PR. Не переписывай архитектуру без необходимости. Если меняешь схему, добавь Alembic migration и model tests. Если меняешь safety/prompt/router/validator/privacy, добавь или обнови тесты. В финале перечисли измененные файлы, проверки и остаточные риски.
```

## Block 1: Safety Gate v2 + Strict Quality Audit

Recommended model: `GPT-5.3-Codex`, reasoning `medium`.

```text
Цель: закрыть реальные safety-промахи русского Telegram-ввода и превратить quality audit в регрессионный gate.

Найденные провалы: "Кошка в судорогах 5 минут", "Дай дозу мелоксикама кошке", "Собака съела шоколад", "Есть ли взаимодействия у гентамицина при ХБП?" могут классифицироваться слишком мягко.

Задачи:
- Усиль app/ai/safety.py: нормализация текста, русские словоформы, "дозу", "судорогах", "съела", "шоколад", "изюм", "ксилит", "лук", "чеснок", "перметрин", "ХБП/ХПН", "почечная недостаточность", interaction-фразы без "+".
- Для emergency/toxicology не выдавать обычный low-risk ответ без triage/clarification.
- Добавь регрессии в app/tests/test_safety_gate.py по реальным русским фразам.
- Усиль scripts/quality_audit.py: проверять must_include, must_not_include, requires_escalation, requires_clarification, expected risk_tags; добавить pass/fail status и CLI flag --fail-on-regression с non-zero exit.
- Обнови app/tests/test_quality_audit_pipeline.py.

Проверки:
- python -m pytest app/tests/test_safety_gate.py app/tests/test_quality_audit_pipeline.py app/tests/test_validators.py -q
- python scripts/quality_audit.py --limit 10 --delay-s 0 --fail-on-regression
- python -m ruff check .
```

Acceptance:

- Реальные фразы выше больше не проходят как обычный safe general answer.
- Audit может падать в CI на явной регрессии.
- Нет уверенных числовых доз без источника и обязательных данных.

## Block 2: Teaching Answer Format v2

Recommended model: `GPT-5.3-Codex`, reasoning `medium`.

```text
Цель: ответы должны обучать специалиста после 5-летнего перерыва, а не быть сухой энциклопедией.

Задачи:
- Обнови app/ai/prompts.py: practical format "короткий ответ -> клиническая логика -> что делать на приеме -> частые ошибки -> как запомнить -> мини-вопрос для самопроверки".
- Для pharmacology: "что проверить перед препаратом", "видовые риски", "когда нужен manual_check".
- Для clinical_cases: "triage -> missing data -> differentials -> minimum database -> next step -> owner explanation".
- Не ослаблять dosage/evidence/safety rules.
- Обнови prompt snapshots в app/tests/snapshots и app/tests/test_prompt_manager.py.
- Добавь 5-10 golden-set кейсов на практичность/дружелюбность без proprietary content.

Проверки:
- python -m pytest app/tests/test_prompt_manager.py app/tests/test_formatting.py -q
- python scripts/quality_audit.py --limit 10 --delay-s 0
- python -m ruff check .
```

Acceptance:

- Default answers are practical, memorable, and Telegram-readable.
- High-risk caveats remain explicit.
- Snapshots document the new answer contract.

## Block 3: Daily Learning Route

Recommended model: `GPT-5.3-Codex`, reasoning `medium`.

```text
Цель: добавить ежедневный учебный маршрут "универ -> практика" в Telegram.

Задачи:
- Добавь команду /today.
- Ответ /today: 15-30 минутный план: 1 мини-кейс, 1 препарат/риск, due cards count, 3 карточки к повторению, 1 reflection question.
- Используй существующие topics/cards/review_events/product_events, без новой сложной схемы если можно.
- Если данных мало, дать стартовый маршрут по кошкам/собакам: triage, рвота/диарея, НПВС у кошек, базовая диагностика.
- Добавь analytics event learning_route_opened.
- Добавь тесты в app/tests/test_telegram_handlers.py или отдельный test_learning_route.py.

Проверки:
- python -m pytest app/tests/test_telegram_handlers.py app/tests/test_learning_service.py -q
- python -m ruff check .
```

Acceptance:

- Пользователь может каждый день открыть один понятный учебный план без ручного выбора команд.
- Empty-state полезен, а не "нет данных".

## Block 4: Cards And Quiz 2.0

Recommended model: `GPT-5.4-mini medium` for simple prompt/test changes; `GPT-5.3-Codex medium` if backend behavior changes broadly.

```text
Цель: карточки закрепляют практическое мышление, а не только факты.

Задачи:
- Улучши LearningService.generate_cards_structured prompt: card_type fact|cloze|case_next_step|risk_check|owner_explain.
- Не создавать dosage cards с числовыми дозами без source/evidence; такие карточки помечать needs_manual_check.
- Добавь leech detection: if lapses >= 2, tag leech и в /review показывать короткую подсказку "разбить карточку".
- Quiz explanations: почему правильный вариант правильный и чем опасны distractors.
- Обнови tests LearningService.

Проверки:
- python -m pytest app/tests/test_learning_service.py app/tests/test_telegram_handlers.py -q
- python -m ruff check .
```

Acceptance:

- Cards become clinically useful and source-linked.
- Unsafe dosage facts are not memorized as prescriptions.

## Block 5: Case Simulator MVP

Recommended model: `GPT-5.3-Codex`, reasoning `medium`; use `high` only if state management grows.

```text
Цель: бот тренирует клиническое мышление, а не сразу выдает финальный ответ.

Задачи:
- Добавь /case and /case_answer или простой inline flow для одного текущего кейса.
- MVP cases: 8-12 virtual cases без proprietary content: рвота у собаки, кошка с одышкой, щенок с кровавой диареей, НПВС risk, пиометра suspicion.
- Flow: кейс -> пользователь пишет вопросы/дифы/план -> бот оценивает по rubric: missing data, red flags, differentials, diagnostics, unsafe assumptions.
- Все real-animal treatment claims должны быть educational/manual_check.
- Записывай product_events: case_started, case_submitted, case_feedback.
- Тесты на user isolation и safety wording.

Проверки:
- python -m pytest app/tests/test_telegram_handlers.py app/tests/test_safety_gate.py -q
- python scripts/quality_audit.py --limit 10 --delay-s 0
- python -m ruff check .
```

Acceptance:

- Есть безопасная виртуальная практика.
- Feedback учит, где была ошибка мышления.

## Block 6: Web Learning Cockpit + Feedback Loop

Recommended model: `GPT-5.4-mini medium` for UI-only work; `GPT-5.3-Codex medium` if backend changes.

```text
Цель: web cabinet должен быть учебным cockpit, а не JSON-admin экраном.

Задачи:
- В web/src/App.jsx заменить raw JSON в Admin/Analytics на читаемые секции: weak topics, due cards, open negative feedback, high-risk count, zero-result searches.
- Добавить обработку feedback status через существующий PATCH /admin/feedback/{id}: new/in_review/resolved/ignored.
- В Settings показать AI routing, source coverage и go/no-go health простым языком.
- Не делать public SaaS UI.
- Обнови web/src/App.test.jsx.

Проверки:
- cd web; npm test; npm run build; npm audit --omit=dev
- python -m ruff check . если менял Python
```

Acceptance:

- Owner can see what to fix next after a study session.
- UI helps triage learning/safety gaps without reading JSON blobs.

## Recommended Order

1. Block 1: Safety Gate v2 + Strict Quality Audit.
2. Block 2: Teaching Answer Format v2.
3. Block 3: Daily Learning Route.
4. Block 4: Cards And Quiz 2.0.
5. Block 5: Case Simulator MVP.
6. Block 6: Web Learning Cockpit + Feedback Loop.

Block 1 should be done before user-facing learning expansion because current audit already found safety misses in realistic phrasing.

