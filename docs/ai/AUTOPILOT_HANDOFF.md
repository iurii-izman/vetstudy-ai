# VetStudy AI Autopilot Handoff

Last updated: 2026-05-03.

This is the first file a new Codex session should read after `AGENTS.md`. It is intentionally shorter and more current than the original long planning docs.

## Current State

- Repository: `git@github.com:iurii-izman/vetstudy-ai.git`.
- Local branch: `main`, synced with `origin/main` at `24fc62e` when this file was created.
- Release line: `v0.1.0-beta.1`.
- Product: private-beta Telegram-first veterinary study assistant for one trusted Russian-speaking veterinary specialist returning to practice after a long break.
- Primary UX: Telegram private supergroup with forum topics.
- Owner/admin UX: FastAPI + React/Vite web cabinet.
- Runtime: Python 3.12, FastAPI, aiogram, PostgreSQL/pgvector, Redis Streams worker, React/Vite.

## What The Prior Sessions Built

The local Codex session index contains a sequence of VetStudy threads from 2026-05-01 through 2026-05-03. Sensitive threads and raw secrets were not copied here. The useful project history is:

1. Designed the original VetStudy AI product and 14 MVP autopilot blocks.
2. Built FastAPI/aiogram/SQLAlchemy/Alembic/pgvector skeleton.
3. Removed unsafe `create_all()` startup behavior and made Alembic the schema path.
4. Added Telegram forum-topic routing, commands, allowlist, topic binding, and inline actions.
5. Built DB repositories, seed subjects, model calls, sessions, messages, memory, flashcards.
6. Added LLM router/provider abstraction, Gemini/OpenAI-compatible providers, fallback, retries, cost logging.
7. Added centralized `PromptManager` with subject/mode prompts.
8. Added first `SafetyGate` for dosage, toxicology, interactions, red flags, and clarifying questions.
9. Added memory/RAG retrieval, semantic scoring, `/search`, summaries, related topics.
10. Added learning loop: cards, quiz, spaced review, Anki/Markdown export.
11. Added document/media ingestion and later replaced in-memory jobs with Redis Streams + worker.
12. Added deploy hardening, health/readiness, backup script, Docker Compose, structured error handling.
13. Added web cabinet with auth, topics, messages, memory search, notes, cards, stats, admin views.
14. Added multi-user groundwork, RBAC, quotas, privacy export/delete endpoints, user isolation tests.
15. Added production readiness: signed web sessions, password hash support, rate limits, Sentry option.
16. Added product analytics, feedback queue, clinical profile, evidence source coverage, scorecard.
17. Prepared GitHub repository, CI, templates, Dependabot, CodeQL, security docs, beta release.
18. Added Windows self-heal/startup scripts and fixed a pgvector search DB failure.
19. Re-audited UX/learning and identified the next highest-ROI work.

## Current Strengths

- The codebase is no longer a prototype-only bot: it has CI, migrations, tests, docs, deployment runbooks, auth, quotas, callbacks, analytics, and backup/recovery notes.
- Telegram inline buttons are real actions, not placeholders.
- User-scoped memory/cards/search and web session binding are covered by tests.
- High-risk answers are wrapped by safety/evidence concepts and audit fixtures.
- Operational docs exist for private beta, release, backup, restore, and Windows self-heal.

## Known Gaps To Respect

- `scripts/quality_audit.py` currently records results but does not yet enforce all `must_include`, `must_not_include`, `requires_escalation`, and `requires_clarification` expectations as a CI-failing gate.
- `SafetyGate` is regex/rule-based and misses some realistic Russian forms unless upgraded. Known missed phrases from the 2026-05-03 audit: `дозу`, `судорогах`, `съела шоколад`, `ХБП` in some contexts.
- Evidence mode is curated/source-aware, not comprehensive clinical verification.
- Uploaded raw file deletion is still a privacy hardening item before broader beta.
- Free provider availability, model quality, and retention terms must be rechecked before public/commercial use.
- Medical accuracy still needs human veterinary review before expansion beyond private beta.

## Development Defaults

- For backend, safety, prompts, migrations, privacy, router, and tests: use `GPT-5.3-Codex` with `medium` reasoning. Use `high` only for hard migrations, cross-module refactors, or safety failures.
- For docs, simple UI polish, and small frontend panels: `GPT-5.4-mini` with `medium` is acceptable.
- Do not use small/mini models for veterinary safety, dosage policy, schema migrations, auth, or privacy deletion.
- Work in focused branches/PRs. Do not batch unrelated UX, safety, schema, and deployment changes together.

## Start-Of-Session Routine

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/autopilot_context.ps1
```

Then read:

1. `AGENTS.md`
2. `docs/ai/AUTOPILOT_HANDOFF.md`
3. `docs/ai/AUTOPILOT_NEXT_BLOCKS.md`
4. The narrow module files for the specific task.

## Safe Check Sets

Narrow safety/prompt work:

```powershell
python -m pytest app/tests/test_safety_gate.py app/tests/test_validators.py app/tests/test_quality_audit_pipeline.py app/tests/test_prompt_manager.py -q
python -m ruff check .
```

Backend full:

```powershell
python -m ruff check .
python -m pytest -q
alembic upgrade head
```

Frontend full:

```powershell
cd web
npm ci
npm test
npm run build
npm audit --omit=dev
```

Private-beta preflight:

```powershell
python scripts/preflight_check.py --db --schema
python scripts/quality_audit.py --limit 10 --delay-s 0
```

## Do Not Copy From Old Threads

Some older sessions contained real local `.env`, provider, Telegram, or owner values during beta setup. Never copy IDs, tokens, keys, passwords, chat IDs, or raw file paths from Codex session logs into tracked files. Use `.env`, secret managers, and redacted docs only.

