# Architecture

VetStudy AI is a small modular beta system. The product boundary is Telegram-first learning with a web owner cabinet, not a public multi-tenant SaaS surface.

## Runtime

```text
Telegram user/group
  -> aiogram handlers
  -> safety gate + topic/session context
  -> LLM router + validators
  -> Postgres memory/messages/cards/feedback
  -> Telegram response + inline actions

Web cabinet
  -> FastAPI /api/web
  -> signed bearer/session auth
  -> Postgres analytics/admin/user data

Document upload
  -> stored file metadata
  -> Redis Stream job
  -> media worker
  -> extracted chunks + embeddings-ready rows
```

## Key Modules

- `app/main.py` - FastAPI app, health/readiness, webhook, lifespan.
- `app/telegram/handlers.py` - Telegram commands, text flow, callbacks, media entrypoints.
- `app/ai/` - prompt manager, router, provider adapters, safety/validation.
- `app/db/` - SQLAlchemy models, sessions, repositories.
- `app/media/` - extractors, storage, Redis stream jobs, worker.
- `app/learning/` - flashcard/review behavior.
- `app/evidence/` - source-aware answer wrapping and high-risk evidence status.
- `app/analytics/` - beta product analytics and funnel reporting.
- `app/web/` - web API and session security.
- `web/` - React/Vite owner cabinet.

## Data Principles

- User-scoped rows are the default.
- Shared Telegram forum topics can be global (`Topic.user_id = NULL`) but are only visible to users with linked sessions/memory/cards, or owner/admin.
- Provider calls are recorded in `model_calls` for cost and debugging.
- Negative feedback, review events, product events, and error events are first-class beta signals.

## Safety Principles

- Telegram allowlist gates all beta access.
- High-risk prompts are detected before generation and validated after generation.
- Numeric dose answers require source-backed context and should degrade to clarification or `needs_manual_check`.
- Web sessions are short-lived and bound to the authenticated Telegram ID.
- Raw secrets and generated audit artifacts are outside git.

## Release Principles

- `main` is the beta baseline after first publication.
- Future work should use issues, feature branches, PR checks, and small AI-agent tasks.
- Schema changes require Alembic migrations and model/test alignment.
- Release readiness is defined by `docs/beta/RELEASE_CHECKLIST.md`.
