# Free API Setup (Beta)

Ниже готовый путь, чтобы вам осталось только вставить ключи.

## 1) Где получить ключи

- Telegram Bot Token: [@BotFather](https://t.me/BotFather)
: команда `/newbot`, после создания скопировать token.

- OpenRouter API Key (primary): [OpenRouter Keys](https://openrouter.ai/keys)
: зарегистрироваться, создать key, проверить что доступна бесплатная модель `:free`.

- Groq API Key (fallback): [Groq Console Keys](https://console.groq.com/keys)
: создать key для fallback-провайдера.

Опционально:
- Gemini key: [Google AI Studio](https://aistudio.google.com/app/apikey)

## 2) Что заполнить в `.env`

Скопируйте `.env.example` в `.env` и заполните только эти поля:

```env
TELEGRAM_BOT_TOKEN=
ALLOWED_TELEGRAM_USER_IDS=<ВАШ_TELEGRAM_USER_ID>
USER_ID_HASH_SALT=<ЛЮБАЯ_ДЛИННАЯ_СТРОКА>
WEB_OWNER_TELEGRAM_ID=<ВАШ_TELEGRAM_USER_ID>
WEB_OWNER_PASSWORD_HASH='<PBKDF2_HASH_ИЛИ_ОСТАВЬТЕ_ПУСТЫМ>'
WEB_OWNER_PASSWORD=<ДЛИННЫЙ_ПАРОЛЬ_ДЛЯ_WEB_ЕСЛИ_HASH_НЕ_ИСПОЛЬЗУЕТСЯ>
WEB_OWNER_TOKEN=<ДЛИННЫЙ_RANDOM_TOKEN_ДЛЯ_WEB>
WEB_SESSION_SECRET=<ДЛИННЫЙ_RANDOM_SECRET_ДЛЯ_SESSION>

OPENROUTER_API_KEY=
GROQ_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=

LLM_HIGH_RISK_PROVIDER=openai
LLM_HIGH_RISK_MODEL=gpt-5.4
LLM_LOW_RISK_PROVIDER=gemini
LLM_LOW_RISK_MODEL=gemini-2.5-flash-lite
LLM_EMBEDDINGS_PROVIDER=openai
LLM_EMBEDDINGS_MODEL=text-embedding-3-small
```

Остальное уже преднастроено в `.env.example` под бесплатный beta-режим:
- primary = Groq (`llama-3.1-8b-instant`) как быстрый provider
- fallback = OpenRouter free model (`openai/gpt-oss-20b:free`)
- cost limits снижены для безопасного теста

Dual-routing поведение:
- high-risk intent/risk_tags идёт в paid high-risk модель (`openai/gpt-5.4` по умолчанию);
- low-risk/general идёт в free low-risk модель (`gemini/gemini-2.5-flash-lite` по умолчанию);
- fallback раздельный: для high-risk сначала `gemini-2.5-pro` (если доступен Gemini key), для low-risk сначала `gemini-2.5-flash`, затем стандартный fallback.

## 3) Готовые адреса/эндпоинты

После запуска сервиса:
- Health: [http://localhost:8000/health](http://localhost:8000/health)
- Readiness: [http://localhost:8000/ready](http://localhost:8000/ready)
- Telegram webhook endpoint (если режим webhook):
  - `https://<your-domain>/telegram/webhook`

## 4) Как запустить

```powershell
docker compose up --build
```

Если локально без Docker (и есть локальная БД):
```powershell
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 5) Как проверить, что генерация работает

1. Открыть бота в Telegram.
2. Отправить `/start`.
3. Отправить `/bind_topic pharmacology`.
4. Отправить вопрос: `Объясни НПВС у кошек кратко`.

Ожидаемо:
- бот отвечает по теме;
- если Groq временно недоступен, должен сработать OpenRouter fallback.

## 6) Быстрая диагностика проблем

- Ошибка `Доступ запрещен`:
  - проверьте `ALLOWED_TELEGRAM_USER_IDS`.

- Ошибка AI-конфигурации:
  - проверьте `OPENROUTER_API_KEY`/`GROQ_API_KEY` и выбранные провайдеры.

- Нет ответа в Telegram:
  - проверьте, что сервис запущен;
  - для polling убедитесь что `TELEGRAM_MODE=polling`;
  - для webhook проверьте публичный `WEBHOOK_URL` и TLS.

