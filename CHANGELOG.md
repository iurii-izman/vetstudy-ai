# Changelog

## v0.1.0-beta.1 - 2026-05-03

Initial beta release candidate.

### Added
- Telegram-first study workflow with topics, memory, search, notes, flashcards, quiz/review, document indexing, and exports.
- FastAPI web cabinet for owner/admin review, topic state, cards, analytics, feedback, costs, and data export.
- LLM router with primary/fallback providers, retry/backoff, cost tracking, safety gate, and post-generation validators.
- Postgres/Alembic schema with pgvector-ready document chunks, user isolation, product analytics, feedback, and review events.
- Schema drift guard for older beta databases stamped at `0008` without `product_events`.
- Redis-backed document indexing jobs for durable beta processing.
- Docker Compose local beta stack with backend, bot, worker, Postgres, and Redis.
- Release docs, runbook, beta checklist, source policy, and AI-agent guardrails.

### Security
- GitHub secret scanning and push protection are enabled on the public repository.
- Web cabinet requires bearer/session authentication; session tokens are bound to the authenticated Telegram ID.
- `.env`, local data, backups, caches, build output, and generated audit artifacts are ignored.

### Known Limits
- Closed/private educational beta only; not approved for public clinical use.
- Medical accuracy still requires human veterinary review of high-risk samples and golden-set expectations.
- Provider terms, data retention, and secrets must be re-checked before broader beta or commercial use.
