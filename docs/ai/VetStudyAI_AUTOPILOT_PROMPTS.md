# VetStudy AI: блоки работ для AI-автопилота

Этот документ продолжает `docs/ai/VetStudyAI_FINAL_SPEC.md`.

Первый промпт из раздела 19 уже запущен и должен создать базовый каркас MVP-1. Ниже идут последующие крупные блоки реализации. Каждый блок можно отдавать AI-автопилоту отдельной задачей после завершения предыдущего.

Общее правило для всех блоков:

- Не переписывать архитектуру без необходимости.
- Не ломать уже работающие команды.
- Перед изменениями читать `docs/ai/VetStudyAI_FINAL_SPEC.md`, текущий `README.md`, `.env.example`, миграции и тесты.
- После каждого блока запускать тесты и обновлять документацию.
- Все настройки моделей, ключей, лимитов и Telegram id должны идти через env/config, не хардкодиться.

## Блок 1. Аудит и стабилизация стартового каркаса

Цель: проверить результат первого автопилота, убрать хрупкости, сделать проект запускаемым локально.

Промпт для AI-автопилота:

```text
Ты senior Python engineer. В проекте VetStudy AI уже создан стартовый каркас по `docs/ai/VetStudyAI_FINAL_SPEC.md`. Проведи инженерный аудит и стабилизируй базу.

Сделай:
1. Прочитай `docs/ai/VetStudyAI_FINAL_SPEC.md`, README.md, .env.example, docker-compose.yml, Alembic migrations, app/config.py и текущие handlers.
2. Проверь, что проект запускается локально через Docker Compose и без Docker, если это предусмотрено README.
3. Исправь ошибки импорта, конфигурации, миграций, типов и async/sync несовместимости.
4. Убедись, что в .env.example есть все переменные:
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
   - ALLOWED_TELEGRAM_USER_IDS
   - DATABASE_URL
   - REDIS_URL, если Redis уже используется
   - LLM_PRIMARY_PROVIDER
   - LLM_PRIMARY_MODEL
   - LLM_FALLBACK_PROVIDER
   - LLM_FALLBACK_MODEL
   - DAILY_COST_LIMIT_USD
   - MONTHLY_COST_LIMIT_USD
5. Добавь make/PowerShell-friendly команды в README:
   - install
   - run local
   - run docker
   - migrate
   - test
6. Проверь, что тесты не требуют реального Telegram/API ключа. Для внешних сервисов используй mocks/fakes.
7. Добавь минимальный smoke test запуска app config и healthcheck.

Acceptance criteria:
- `pytest` проходит.
- `alembic upgrade head` работает на чистой базе.
- `docker compose up` поднимает backend и БД.
- README позволяет новому разработчику запустить проект без догадок.
- Никакие реальные API ключи не попали в репозиторий.

В финальном ответе перечисли измененные файлы, команды проверки и оставшиеся риски.
```

Действия разработчика после блока:

- Запустить проект локально на своей машине.
- Проверить, что `.env` создан из `.env.example`.
- Убедиться, что реальные секреты не закоммичены.
- Если используется Supabase вместо локального Postgres, создать проект и прописать `DATABASE_URL`.

## Блок 2. Telegram Forum Topics и базовый UX

Цель: довести Telegram-часть до реального использования в приватной группе с темами.

Промпт для AI-автопилота:

```text
Ты senior Python/Telegram engineer. Реализуй production-ready Telegram UX для VetStudy AI.

Контекст:
- Основной интерфейс: приватная Telegram-супергруппа с Forum Topics.
- Бот должен отвечать в том же message_thread_id.
- Каждый Telegram topic соответствует записи topics в БД.

Сделай:
1. Реализуй обработку message_thread_id для всех входящих сообщений.
2. Добавь команду /start с проверкой allowlist.
3. Добавь /help с кратким списком команд.
4. Добавь /topics:
   - показывает известные темы из БД;
   - показывает текущий Telegram thread id;
   - объясняет, если topic не привязан.
5. Добавь /bind_topic <slug_or_name> для привязки текущего Telegram topic к subject/topic в БД.
6. Добавь /create_default_topics:
   - если у бота есть права can_manage_topics, создать стартовые topics;
   - сохранить telegram_thread_id в БД;
   - если прав нет, вывести понятную инструкцию.
7. Добавь корректное разбиение длинных ответов на сообщения Telegram.
8. Под каждым AI-ответом добавь inline-кнопки:
   - Сохранить
   - Кратко
   - Глубже
   - Карточки
   - Тест
   - Связанные темы
9. Добавь обработчики callback_data, пока можно с mock/no-op для функций, которые будут реализованы позже.
10. Покрой тестами:
   - сообщение в известном topic;
   - сообщение в неизвестном topic;
   - allowlist;
   - split длинного ответа;
   - callback parsing.

Acceptance criteria:
- Бот всегда отвечает в исходный forum topic.
- Неавторизованный пользователь не может пользоваться ботом.
- Разработчик может привязать topic к БД командой /bind_topic.
- Длинные ответы не падают из-за лимита Telegram.
- Тесты проходят без реального Telegram.

В финальном ответе дай инструкцию ручной настройки Telegram-группы.
```

Действия разработчика после блока:

- Создать бота через BotFather.
- Создать приватную супергруппу Telegram.
- Включить Topics/Темы.
- Добавить бота администратором.
- Выдать право управлять темами, если нужно автосоздание.
- Отключить privacy mode у бота через BotFather, если требуется читать сообщения в группе.
- Прописать `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ALLOWED_TELEGRAM_USER_IDS`.
- Прогнать ручной тест: написать вопрос в каждом topic и проверить, что ответ пришел туда же.

## Блок 3. База данных, репозитории и seed-данные

Цель: сделать устойчивый слой данных для сообщений, памяти, карточек, вызовов моделей и тем.

Промпт для AI-автопилота:

```text
Ты backend engineer. Доведи слой БД VetStudy AI до MVP-1.

Сделай:
1. Сверь модели SQLAlchemy и Alembic migrations с разделом 11 `docs/ai/VetStudyAI_FINAL_SPEC.md`.
2. Реализуй таблицы:
   - users
   - subjects
   - topics
   - sessions
   - messages
   - memory_items
   - model_calls
   - flashcards
3. Добавь индексы:
   - telegram_user_id unique
   - telegram_thread_id
   - active session by user/topic
   - memory_items by user/topic/kind/tags
   - vector index для embedding, если pgvector доступен.
4. Реализуй repository/service слой без SQL в Telegram handlers.
5. Добавь seed-команду или Alembic seed script для subjects:
   - pharmacology
   - surgery
   - internal_medicine
   - anatomy
   - parasitology
   - diagnostics
   - clinical_cases
   - exam
   - general
6. Добавь idempotent создание пользователя по telegram_user_id.
7. Добавь создание/получение active session для user/topic.
8. Добавь сохранение user/assistant messages и model call metadata.
9. Добавь тесты репозиториев на test database.

Acceptance criteria:
- Миграции применяются на пустую базу.
- Seed можно запускать повторно без дублей.
- Telegram handlers используют services/repositories, а не прямой SQL.
- Есть тесты на создание пользователя, topic, session, messages, flashcards.

В финальном ответе перечисли схему, индексы и команды миграции/seed.
```

Действия разработчика после блока:

- Выбрать финальную БД для MVP: локальный Postgres, Supabase или VPS Postgres.
- Если Supabase: включить extension `vector`, проверить права пользователя и лимиты free tier.
- Настроить backup: хотя бы ежедневный dump или Supabase backups/export.
- Проверить, что seed-темы соответствуют реальным Telegram topics.

## Блок 4. LLM Router, провайдеры, лимиты расходов и fallback

Цель: изолировать работу с AI, не привязывать проект к одной модели и контролировать расходы.

Промпт для AI-автопилота:

```text
Ты AI platform engineer. Реализуй LLMRouter для VetStudy AI.

Требования:
- Telegram handlers не должны напрямую вызывать OpenAI/Gemini/OpenRouter/Groq.
- Все модели и провайдеры настраиваются через config/env.
- Должен быть mock provider для тестов.

Сделай:
1. Спроектируй интерфейс LLMProvider:
   - generate(messages, system_prompt, response_format=None, tools=None, metadata=None)
   - embed(texts)
   - estimate_cost or return usage metadata when provider gives usage.
2. Реализуй LLMRouter:
   - primary provider;
   - fallback provider;
   - separate provider/model for classification;
   - separate provider/model for summaries;
   - separate provider/model for embeddings.
3. Реализуй минимум:
   - MockProvider для tests/dev;
   - один реальный provider по текущим env проекта;
   - provider skeletons для остальных без падений при отсутствии ключа.
4. Добавь retry policy:
   - timeout;
   - rate limit;
   - transient errors;
   - fallback on provider failure.
5. Добавь CostGuard:
   - daily limit;
   - monthly limit;
   - per-request max tokens;
   - логирование в model_calls.
6. Добавь structured logging по каждому AI вызову.
7. Добавь тесты:
   - primary success;
   - primary failure -> fallback;
   - missing API key gives clear error;
   - daily limit exceeded;
   - model_calls записываются.

Acceptance criteria:
- Можно сменить модель через .env без правки кода.
- При падении primary provider бот возвращает ответ через fallback или понятную ошибку.
- Расходы/usage логируются.
- Тесты не требуют реальных ключей.

В финальном ответе дай таблицу env-переменных для AI layer.
```

Действия разработчика после блока:

- Создать API ключи выбранных провайдеров.
- Прописать ключи только в локальный `.env`/секреты хостинга.
- Проверить billing limits в кабинетах провайдеров.
- Выбрать реальные default-модели на текущую дату.
- Сделать 3-5 тестовых запросов и сверить фактическую стоимость/лимиты.

## Блок 5. PromptManager и предметные режимы ответа

Цель: вынести промпты в управляемый слой и реализовать режимы ответа.

Промпт для AI-автопилота:

```text
Ты prompt engineer и backend engineer. Реализуй PromptManager для VetStudy AI.

Контекст:
- Пользователь: русскоязычный ветеринарный специалист после университета.
- Цель: быстро влиться в реальную практику с кошками и собаками.
- Стиль: практично, точно, структурно, с примерами, без лишней воды.

Сделай:
1. Создай PromptManager, который собирает system prompt из:
   - глобального профиля;
   - subject prompt;
   - mode prompt;
   - safety rules;
   - retrieved memory;
   - краткой истории текущей сессии.
2. Реализуй режимы:
   - short
   - practical
   - deep
   - exam
   - protocol
   - cards
   - quiz
3. Реализуй subject prompts:
   - pharmacology
   - surgery
   - internal_medicine
   - anatomy
   - parasitology
   - diagnostics
   - clinical_cases
   - general
4. Для pharmacology сделай отдельный шаблон:
   - краткий вывод;
   - когда применяют;
   - механизм;
   - риски;
   - кошки/собаки;
   - дозировки только через safety gate;
   - взаимодействия;
   - практические ошибки;
   - что запомнить;
   - связанные темы.
5. Добавь команду /mode и сохранение режима в session/user settings.
6. Добавь tests/snapshots для сборки prompt по разным subjects/modes.

Acceptance criteria:
- Prompt assembly покрыт тестами.
- Изменение режима реально меняет структуру ответа.
- Все промпты лежат в одном понятном месте, не размазаны по handlers.
- Pharmacology prompt соблюдает правила осторожности по дозировкам.

В финальном ответе покажи краткий список режимов и где они настраиваются.
```

Действия разработчика после блока:

- Прочитать все предметные промпты глазами.
- На 10 реальных учебных вопросах проверить стиль: не слишком длинно, не слишком сухо.
- Поправить формулировки под пользователя.
- Согласовать, какие режимы должны быть кнопками по умолчанию.

## Блок 6. Veterinary Safety Gate для дозировок и клинических рисков

Цель: не позволить боту самоуверенно давать опасные ветеринарные рекомендации.

Промпт для AI-автопилота:

```text
Ты backend engineer с фокусом на medical/veterinary safety. Реализуй SafetyGate для VetStudy AI.

Контекст:
- Проект учебный, но пользователь будет задавать практические вопросы.
- Стартовые виды: кошки и собаки.
- Дозировки разрешены, но только осторожно и с недостающими уточнениями.

Сделай:
1. Реализуй классификацию intent/risk:
   - general_education
   - dosage_request
   - clinical_case
   - emergency_or_red_flag
   - toxicology
   - drug_interaction
   - uncertain_source
2. Для dosage_request проверь обязательные поля:
   - species;
   - weight;
   - age/life stage, если релевантно;
   - indication/diagnosis;
   - drug form/concentration, если релевантно;
   - route;
   - pregnancy/lactation, если релевантно;
   - liver/kidney/heart status, если релевантно;
   - current drugs.
3. Если данных не хватает, бот не должен отвечать дозой. Он должен задать короткий список уточняющих вопросов.
4. Добавь safety disclaimers без лишнего морализаторства:
   - "проверь по актуальной инструкции/формуляру";
   - "это учебная помощь, не замена очному решению врача";
   - "при красных флагах нужна срочная очная помощь".
5. Реализуй список high-risk patterns для кошек и собак:
   - NSAIDs у кошек;
   - paracetamol/acetaminophen у кошек;
   - ivermectin/MDR1 risk у собак;
   - steroids + NSAIDs;
   - aminoglycosides + kidney risk;
   - anticoagulants;
   - anesthesia/sedation combinations.
6. SafetyGate должен возвращать:
   - allow;
   - ask_clarifying_questions;
   - answer_with_warning;
   - refuse_emergency_instruction_and_triage.
7. Покрой тестами минимум 20 safety cases.

Acceptance criteria:
- `дай дозу мелоксикама кошке` без массы -> уточняющие вопросы.
- `парацетамол кошке` -> high-risk warning.
- `собака колли и ивермектин` -> MDR1 warning.
- `НПВС + преднизолон` -> interaction warning.
- Общие учебные вопросы не блокируются.

В финальном ответе перечисли реализованные risk patterns и тестовые сценарии.
```

Действия разработчика после блока:

- Попросить ветеринарного специалиста просмотреть safety rules.
- Проверить, что бот не становится бесполезным из-за чрезмерных блокировок.
- Решить, в каких странах/регионах будут проверяться инструкции и формуляры на следующих этапах.

## Блок 7. Память, RAG, embeddings и связанные темы

Цель: сделать долгую память, поиск по смыслу и "ссылки как в Википедии".

Промпт для AI-автопилота:

```text
Ты backend/AI retrieval engineer. Реализуй MemoryService для VetStudy AI.

Сделай:
1. Реализуй embedding pipeline для messages/memory_items:
   - после сохранения assistant answer создавать memory_item;
   - считать embedding;
   - сохранять tags, title, topic_id, source_message_id.
2. Реализуй retrieval:
   - фильтр по user_id;
   - приоритет текущего topic;
   - возможность поиска across topics для связанных тем;
   - top_k configurable.
3. Реализуй /search <query>:
   - semantic search;
   - вывод 3-7 результатов;
   - ссылка/указание topic и дата;
   - короткий фрагмент.
4. Реализуй topic summary:
   - /summary current session;
   - /summary topic;
   - автоматическое обновление summary после N сообщений.
5. Реализуй extraction tags:
   - препараты;
   - виды животных;
   - болезни/синдромы;
   - процедуры;
   - риски;
   - exam/practice.
6. Реализуй "Связанные темы":
   - по embeddings;
   - по tags;
   - по subject graph rules.
7. Добавь tests:
   - retrieval не смешивает пользователей;
   - retrieval приоритетно ищет внутри topic;
   - cross-topic links работают;
   - /search форматирует результаты.

Acceptance criteria:
- Старые ответы находятся по смыслу, даже без точного совпадения слов.
- Контексты разных topics не смешиваются без причины.
- Связанные темы появляются в конце ответа или по кнопке.
- Embeddings можно отключить/замокать в tests.

В финальном ответе опиши retrieval strategy и ограничения.
```

Действия разработчика после блока:

- Выбрать embedding model и размерность, затем зафиксировать в БД.
- Если меняется embedding model, продумать re-embedding всех memory_items.
- На 20 реальных вопросах проверить качество поиска.
- Удалить или поправить мусорные теги, если extraction слишком шумный.

## Блок 8. Карточки, тесты, интервальное повторение и экспорт Anki

Цель: превратить ответы в учебный материал, а не просто архив.

Промпт для AI-автопилота:

```text
Ты backend engineer для educational product. Реализуй учебные функции VetStudy AI: flashcards, quiz, spaced repetition, export.

Сделай:
1. Реализуй /cards:
   - по последнему AI-ответу;
   - по текущему topic summary;
   - по search results, если выбран результат.
2. Карточка должна иметь:
   - front;
   - back;
   - topic_id;
   - source_message_id;
   - tags.
3. Реализуй /quiz:
   - 5-10 вопросов;
   - варианты ответов где уместно;
   - правильный ответ;
   - объяснение.
4. Реализуй кнопки:
   - "Знал"
   - "Не знал"
   - "Повторить позже"
5. Реализуй простую spaced repetition логику:
   - initial interval;
   - ease;
   - due_at;
   - /review показывает карточки due now.
6. Реализуй /export anki:
   - CSV формат front/back/tags/source;
   - корректное escaping;
   - отдача файлом в Telegram.
7. Реализуй /export markdown:
   - topic notes;
   - saved notes;
   - cards.
8. Добавь тесты генерации карточек, сохранения, review flow и CSV export.

Acceptance criteria:
- Из любого нормального ответа можно сделать карточки.
- Карточки связаны с источником.
- /review работает без веб-кабинета.
- Anki CSV импортируемый и не ломается на переносах строк/запятых.

В финальном ответе дай пример CSV и список команд.
```

Действия разработчика после блока:

- Импортировать тестовый CSV в Anki и проверить кодировку.
- Настроить желаемые интервалы повторения.
- Проверить, что карточки не получаются слишком длинными.
- Решить, нужен ли в будущем AnkiConnect или достаточно CSV.

## Блок 9. Голосовые, фото, OCR и документы

Цель: добавить удобный ввод с телефона и базу знаний из материалов.

Промпт для AI-автопилота:

```text
Ты backend engineer. Реализуй мультимодальный ввод для VetStudy AI.

Сделай поэтапно:
1. Voice:
   - принимать Telegram voice/audio;
   - скачивать файл;
   - отправлять в speech-to-text provider через LLMRouter/TranscriptionRouter;
   - сохранять transcript как user message;
   - отвечать как на обычный текст.
2. Images:
   - принимать photo/document image;
   - сохранять metadata;
   - если включен OCR provider, извлекать текст;
   - если включена vision model, делать краткое описание;
   - явно предупреждать, что качество OCR/фото может ошибаться.
3. Documents:
   - принимать PDF/docx/txt/md;
   - сохранять файл;
   - извлекать текст;
   - нарезать chunks;
   - создавать memory_items kind=document_chunk;
   - embeddings;
   - команда /docs показывает загруженные документы.
4. Добавь file size limits и безопасные ошибки.
5. Добавь background jobs для тяжелого парсинга.
6. Добавь tests с маленькими fixture-файлами.

Acceptance criteria:
- Голосовой вопрос превращается в текст и получает ответ.
- Фото/скриншот можно обработать или получить понятное сообщение, почему нельзя.
- PDF добавляется в память и участвует в search/RAG.
- Большие файлы не блокируют Telegram handler.

В финальном ответе перечисли поддержанные форматы и ограничения размера.
```

Действия разработчика после блока:

- Выбрать speech-to-text/OCR/vision провайдеры и оценить стоимость.
- Проверить качество распознавания русской речи.
- Загрузить 2-3 реальных PDF/фото конспектов и посмотреть качество chunking.
- Решить политику хранения файлов и сроков удаления.

## Блок 10. Evidence mode и проверка источниками

Цель: добавить режим, где бот сверяется с доверенными источниками и маркирует уверенность.

Промпт для AI-автопилота:

```text
Ты AI engineer. Реализуй Evidence Mode для VetStudy AI.

Контекст:
- В обычном режиме бот может отвечать из модели и памяти.
- В evidence mode бот должен искать подтверждение в доверенных источниках или пользовательских документах.
- Особенно важно для дозировок, противопоказаний, токсичности и взаимодействий.

Сделай:
1. Добавь команду /verify_last и кнопку "Проверить источниками".
2. Добавь SourceService с источниками:
   - пользовательские документы в memory_items kind=document_chunk;
   - web search provider interface, если доступен;
   - список trusted domains/config.
3. Реализуй evidence pipeline:
   - извлечь claims из последнего ответа;
   - найти подтверждающие фрагменты;
   - пометить claim as supported/unsupported/conflicting/needs_manual_check;
   - вернуть короткий отчет.
4. Для дозировок:
   - если нет надежного источника, явно писать "требует проверки по актуальной инструкции/формуляру";
   - не придумывать ссылки.
5. Сохранять citations/source snippets в БД.
6. Добавить тесты на:
   - supported claim из пользовательского документа;
   - unsupported claim;
   - conflicting claim;
   - no source found.

Acceptance criteria:
- Последний ответ можно проверить кнопкой.
- Система не выдумывает источники.
- Claims получают статус проверки.
- Evidence mode работает хотя бы по загруженным документам без веба.

В финальном ответе опиши, какие источники реально подключены и что осталось ручным.
```

Действия разработчика после блока:

- Решить, какие web/source APIs можно использовать легально и финансово.
- Проверить правила использования Merck/FDA/EMA/других источников.
- Если нужны платные справочники, обеспечить легальный доступ пользователя.
- На опасных темах вручную проверить, что бот не фальсифицирует цитаты.

## Блок 11. Наблюдаемость, backup, деплой и эксплуатация 24/7

Цель: сделать систему стабильной для ежедневного использования.

Промпт для AI-автопилота:

```text
Ты DevOps/backend engineer. Подготовь VetStudy AI к стабильному деплою.

Сделай:
1. Dockerfile production quality.
2. docker-compose для local dev:
   - backend;
   - postgres;
   - redis, если используется.
3. Healthchecks:
   - /health;
   - /ready, проверяет DB и optional Redis.
4. Structured logging:
   - request id;
   - telegram user id hash или safe id;
   - provider/model;
   - latency;
   - error category.
5. Error handling:
   - понятные сообщения пользователю;
   - stack traces только в logs.
6. Backup:
   - script для pg_dump;
   - restore instruction;
   - scheduled job instructions.
7. Deployment docs:
   - VPS;
   - Railway/Fly/Render;
   - Supabase DB.
8. Secrets handling:
   - .env.example;
   - no secrets in repo;
   - production env docs.
9. Add minimal CI:
   - lint;
   - tests;
   - migration check.

Acceptance criteria:
- Новый сервер можно поднять по README.
- Есть backup/restore инструкция.
- Ошибки AI/Telegram/DB логируются и не ломают процесс.
- CI ловит базовые регрессии.

В финальном ответе дай пошаговую deploy-инструкцию и список обязательных секретов.
```

Действия разработчика после блока:

- Купить/выбрать хостинг или настроить Railway/Fly/Render.
- Прописать production secrets.
- Настроить домен/webhook, если используется webhook.
- Проверить firewall.
- Проверить backup restore на тестовой базе, а не только создание backup.
- Настроить мониторинг падения процесса.

## Блок 12. Веб-кабинет

Цель: добавить удобный архив, дерево тем, поиск, карточки и статистику.

Промпт для AI-автопилота:

```text
Ты full-stack engineer. Реализуй веб-кабинет VetStudy AI как отдельный этап после Telegram MVP.

Контекст:
- Telegram остается основным быстрым интерфейсом.
- Веб нужен для архива, поиска, редактирования заметок, карточек, статистики и будущей админки.

Сделай:
1. Выбери минимальный frontend stack, совместимый с проектом:
   - Next.js или React/Vite.
2. Реализуй backend API endpoints:
   - auth для одного пользователя на MVP;
   - list subjects/topics;
   - list sessions/messages;
   - search memory;
   - saved notes;
   - flashcards;
   - stats.
3. Реализуй UI:
   - левое дерево тем;
   - центральный список ответов/заметок;
   - поиск;
   - карточки на повторение;
   - страница topic summary;
   - настройки.
4. Не делай маркетинговый landing page. Первый экран - рабочий кабинет.
5. Добавь responsive layout для телефона и desktop.
6. Добавь tests:
   - API;
   - basic frontend render;
   - search flow.

Acceptance criteria:
- Можно открыть веб и найти старый ответ быстрее, чем в Telegram.
- Можно просмотреть карточки и статистику.
- Веб не ломает Telegram MVP.
- Auth достаточен для одного владельца.

В финальном ответе дай URL локального dev-сервера и список реализованных экранов.
```

Действия разработчика после блока:

- Выбрать домен или приватный доступ.
- Настроить HTTPS.
- Проверить доступ с телефона.
- Решить, нужен ли полноценный login или достаточно временного single-user auth.
- Вручную пройти основные сценарии поиска/карточек.

## Блок 13. Админка, multi-user и подготовка к продукту

Цель: подготовить систему к использованию не только одной девушкой.

Промпт для AI-автопилота:

```text
Ты product-minded full-stack/backend engineer. Подготовь VetStudy AI к multi-user продукту.

Перед началом проверь, что MVP стабильно работает для одного пользователя.

Сделай:
1. Ввести роли:
   - owner;
   - user;
   - admin.
2. Пересмотреть все queries на user isolation.
3. Добавить user onboarding:
   - создание профиля;
   - выбор языка;
   - выбор специализации;
   - стартовые subjects.
4. Добавить admin panel:
   - пользователи;
   - usage;
   - costs;
   - errors;
   - model settings.
5. Добавить quotas:
   - messages/day;
   - cost/month;
   - premium model limit.
6. Подготовить billing abstraction, но не обязательно подключать платежи в этом блоке.
7. Добавить privacy/export/delete user data:
   - export all data;
   - delete account;
   - delete topic/session.
8. Добавить audit tests на изоляцию пользователей.

Acceptance criteria:
- Данные одного пользователя не видны другому.
- Owner/admin видит usage и errors.
- Есть квоты и cost protection.
- Есть экспорт/удаление данных.

В финальном ответе перечисли изменения в модели данных и риски перед платежами.
```

Действия разработчика после блока:

- Подготовить политику приватности и пользовательское соглашение.
- Проконсультироваться по юридическим формулировкам medical/veterinary disclaimer.
- Решить платежную систему и страну регистрации.
- Провести ручной security review.
- Не открывать публичный доступ, пока не проверены изоляция пользователей и лимиты расходов.

## Блок 14. Финальная полировка качества и beta-тест

Цель: превратить набор функций в удобный стабильный продукт.

Промпт для AI-автопилота:

```text
Ты principal engineer и QA lead. Проведи финальную полировку VetStudy AI перед beta-тестом.

Сделай:
1. Составь end-to-end test plan по сценариям:
   - новый пользователь;
   - вопрос в фармакологии;
   - дозировка с недостаточными данными;
   - клинический случай;
   - поиск старого ответа;
   - карточки;
   - тест;
   - экспорт;
   - voice/photo/PDF, если реализованы;
   - provider failure;
   - cost limit exceeded.
2. Добавь недостающие automated tests там, где возможно.
3. Проведи code review:
   - security;
   - secrets;
   - user isolation;
   - migrations;
   - error handling;
   - Telegram edge cases.
4. Проверь качество ответов:
   - 50 тестовых вопросов;
   - классифицируй проблемы: слишком длинно, неточно, слишком осторожно, не спросил уточнения, плохо форматирует.
5. Создай `docs/beta/BETA_TEST_GUIDE.md`:
   - как пользоваться;
   - какие команды есть;
   - что нельзя воспринимать как назначение лечения;
   - как сообщать об ошибках.
6. Создай `docs/beta/KNOWN_LIMITATIONS.md`.

Acceptance criteria:
- Есть beta guide.
- Есть known limitations.
- Критичные баги исправлены или явно зафиксированы.
- Проект готов к 1-2 неделям реального использования.

В финальном ответе дай список оставшихся рисков и план beta-теста.
```

Действия разработчика после блока:

- Провести реальный beta-тест 1-2 недели.
- Собрать вопросы, где бот ошибся или был неудобен.
- Отметить, какие функции реально нужны, а какие лишние.
- Не масштабировать проект до исправления проблем safety, стоимости и приватности.

## Рекомендуемый порядок запуска блоков

1. Блок 1: аудит стартового каркаса.
2. Блок 2: Telegram Forum UX.
3. Блок 3: БД и seed.
4. Блок 4: LLM Router.
5. Блок 5: PromptManager.
6. Блок 6: SafetyGate.
7. Блок 7: Memory/RAG.
8. Блок 8: карточки/тесты/экспорт.
9. Блок 11: деплой и эксплуатация.
10. Блок 9: голос/фото/PDF.
11. Блок 10: Evidence mode.
12. Блок 12: веб-кабинет.
13. Блок 13: multi-user/product.
14. Блок 14: beta polish.

Блоки 9, 10 и 12 можно менять местами после MVP-1. Если пользователь активно пользуется Telegram и не загружает материалы, раньше делать карточки, память и деплой. Если главная боль - точность по источникам, раньше делать Evidence mode и документы.
