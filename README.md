# VetStudy AI

VetStudy AI is a Telegram-first educational assistant for veterinary study, virtual case practice, notes, flashcards, retrieval, and beta feedback loops.

> Educational beta only. VetStudy AI does not create a veterinarian-client-patient relationship, diagnosis, prescription, dosage authorization, or treatment plan for real animals. AI output can be incomplete or wrong and must be checked against current labels, formularies, and clinical judgment.

## Status

- Release line: `v0.1.0-beta.1`
- Audience: private closed beta for trusted study use
- Primary interface: Telegram bot with forum topics
- Operator interface: FastAPI web cabinet
- Deployment target: Docker Compose or container platform with Postgres and Redis

## Product Surface

- Telegram commands: `/start`, `/help`, `/topics`, `/bind_topic`, `/create_default_topics`, `/new`, `/mode`, `/summary`, `/search`, `/save`, `/cards`, `/quiz`, `/review`, `/docs`, `/export`
- Learning memory: user-scoped notes, summaries, saved answers, search, Anki/Markdown exports
- Flashcards: generation, spaced-review actions, review event tracking
- Documents: TXT/MD/PDF/DOCX extraction and Redis-backed indexing jobs
- AI safety: allowlist, quota guard, high-risk detection, prompt policy, post-generation validators, model fallback
- Admin: provider costs, feedback, errors, topic graph, product analytics, evidence source coverage

## Stack

- Python 3.12, FastAPI, aiogram
- PostgreSQL with pgvector-ready schema
- Redis Streams for document indexing jobs
- Alembic migrations
- React + Vite web cabinet
- Docker Compose local beta stack

## Quick Start

```bash
cp .env.example .env
```

Fill required secrets in `.env`, then run:

```bash
docker compose up --build
```

Verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

For provider setup, use `docs/setup/FREE_API_SETUP.md`.

## Local Development

Backend:

```bash
python -m pip install -r requirements-dev.lock
python -m pip install -e . --no-deps
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Telegram polling:

```bash
python -m app.run_polling
```

Document worker:

```bash
python -m app.media.worker
```

Frontend:

```bash
cd web
npm ci
npm run dev
```

## Validation

```bash
python -m ruff check .
python -m pytest -q
alembic upgrade head
cd web && npm test && npm run build
```

Beta preflight:

```bash
python scripts/preflight_check.py --db --schema --provider
python scripts/quality_audit.py
python scripts/project_scorecard.py --database-url "$DATABASE_URL"
```

The quality audit writes generated review artifacts under `artifacts/quality_audit/`; those files are intentionally ignored.

## Environment

Required for beta:

- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`
- `REDIS_URL`
- `USER_ID_HASH_SALT`
- `WEB_OWNER_TELEGRAM_ID`
- `WEB_OWNER_PASSWORD_HASH` or `WEB_OWNER_PASSWORD`
- `WEB_OWNER_TOKEN`
- `WEB_SESSION_SECRET`
- at least one provider key: `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, or `GEMINI_API_KEY`

Recommended:

- `APP_ENV=prod`
- `DEBUG=false`
- `TELEGRAM_MODE=polling` for local private beta, `webhook` for hosted deployment
- `ALLOWED_TELEGRAM_USER_IDS=<comma-separated ids>`
- low daily/monthly cost limits until provider behavior is proven

## Documentation

- `docs/beta/RUNBOOK.md` - staging/prod operations
- `docs/beta/RELEASE_CHECKLIST.md` - beta release checklist
- `docs/beta/BETA_TEST_GUIDE.md` - manual Telegram/web test plan
- `docs/beta/CLOSED_BETA_DECISIONS.md` - beta policy decisions and residual manual work
- `docs/beta/KNOWN_LIMITATIONS.md` - current limits and go/no-go risks
- `docs/ARCHITECTURE.md` - runtime modules and data flow
- `quality/dosage_policy_transnistria.md` - numeric dosage source policy
- `AGENTS.md` - AI-agent guardrails for future autonomous work

## Security

- `.env`, local data, backups, caches, build output, and audit artifacts are ignored.
- GitHub secret scanning and push protection should stay enabled.
- Web sessions are HMAC-signed, time-limited, and bound to the authenticated Telegram ID.
- Prefer `WEB_OWNER_PASSWORD_HASH` for deployed environments.
- See `SECURITY.md` for reporting and rotation guidance.

## Release

This repository is public for beta review, but it is not open source. See `LICENSE`.

Before expanding beyond private beta:

- rotate runtime secrets;
- complete Telegram smoke in the real private group;
- review quality audit outputs with a human veterinary reviewer;
- verify restore from backup on a production-like database;
- re-check provider terms, retention, pricing, and data-processing settings.
