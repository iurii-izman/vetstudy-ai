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

- Telegram commands: `/start`, `/help`, `/profile`, `/status`, `/topics`, `/bind_topic`, `/create_default_topics`, `/new`, `/mode`, `/evidence`, `/why`, `/summary`, `/search`, `/save`, `/cards`, `/quiz`, `/review`, `/today`, `/case`, `/case_answer`, `/docs`, `/export`
- Learning memory: user-scoped notes, summaries, saved answers, search, Anki/Markdown exports
- Flashcards: generation, spaced-review actions, review event tracking
- Documents: TXT/MD/PDF/DOCX extraction and Redis-backed indexing jobs
- AI safety: allowlist, quota guard, high-risk detection, prompt policy, post-generation validators, model fallback, short-lived provider circuit breaker
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

If `WEB_OWNER_PASSWORD_HASH` contains `$` symbols (PBKDF2 format), wrap it in single quotes in `.env`:

```env
WEB_OWNER_PASSWORD_HASH='$pbkdf2-sha256$...'
```

Verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Web dashboard address:
- API/health endpoints: `http://localhost:8000`
- Frontend dev server (when running `cd web && npm run dev`): `http://localhost:5173`
- `http://localhost:1455` is not used by this repository.

For provider setup, use `docs/setup/FREE_API_SETUP.md`.

Dual risk routing (beta default):
- high-risk intents/tags (`dosage_request`, `toxicology`, `emergency_or_red_flag`, `drug_interaction`, `clinical_case`, `uncertain_source`) route to `LLM_HIGH_RISK_PROVIDER/LLM_HIGH_RISK_MODEL` (default `openai/gpt-5.4`);
- low-risk study queries route to `LLM_LOW_RISK_PROVIDER/LLM_LOW_RISK_MODEL` (default `gemini/gemini-2.5-flash-lite`);
- fallbacks are per-route: high-risk tries `gemini-2.5-pro` (if Gemini is configured), low-risk tries `gemini-2.5-flash` (if configured), then normal `LLM_FALLBACK_PROVIDER/MODEL`.

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

Note: `app.run_polling` no longer starts the media worker in-process. Run worker as a separate process/service.
Worker diagnostics (queue health/readiness):

```bash
python -m app.media.worker --diagnose
python -m app.media.worker --diagnose --fail-on-stall
```

Frontend:

```bash
cd web
npm ci
npm run dev
```

## Windows Auto-Recovery (after reboot)

For local private beta on Windows, first try scheduled self-heal tasks:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install_selfheal_tasks.ps1
```

If you want elevated tasks, run the same command from Administrator PowerShell with `-RunElevated`.

If Task Scheduler is blocked by system policy, use Startup-folder watchdog fallback:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install_startup_watchdog.ps1
```

What this gives:

- task `VetStudyAI-Autostart`: runs at logon, starts compose stack, waits for `http://localhost:8000/ready`, runs deep preflight (`--db --schema`);
- task `VetStudyAI-SelfHeal-10min`: every 10 minutes ensures services are up, checks readiness, runs quick preflight (`--db`), and captures recent logs on failure;
- or Startup watchdog launcher (`VetStudyAI-Watchdog.cmd`) that runs deep check once, then quick checks every 10 minutes;
- `bot` has Telegram `getMe` healthcheck; self-heal restarts bot if it becomes unhealthy;
- docker services use `restart: unless-stopped`, so containers recover after Docker restarts.

Manual one-click recovery command (can be attached to a shortcut):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/ensure_stack.ps1 -DeepChecks
```

Logs are written to `artifacts/ops_logs/`.

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
python scripts/quality_audit.py --limit 10 --delay-s 0 --fail-on-regression --min-overall-quality 62 --max-generic-rate 0.35 --min-clarification-hit-rate 0.8
python scripts/project_scorecard.py --database-url "$DATABASE_URL"
python scripts/restore_verify.py --database-url "$DATABASE_URL"
```

Quality degradation is treated as CI-failing when answers become too generic, omit required clarifying questions, or lose expected clinical specificity for the golden cases.  
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
- dual-risk routing variables: `LLM_LOW_RISK_PROVIDER`, `LLM_LOW_RISK_MODEL`, `LLM_HIGH_RISK_PROVIDER`, `LLM_HIGH_RISK_MODEL`
- at least one provider key: `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, or `GEMINI_API_KEY`
- for `APP_ENV=prod`, set non-mock `LLM_EMBEDDINGS_PROVIDER`, non-empty `LLM_EMBEDDINGS_MODEL`, and a matching provider API key

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
- `docs/ai/AUTOPILOT_HANDOFF.md` - current handoff for future Codex/IDE sessions
- `docs/ai/AUTOPILOT_NEXT_BLOCKS.md` - current ordered prompts for the next autopilot PRs
- `docs/ai/CURSOR_MCP_SETUP.md` - Cursor project-rules and safe MCP setup guidance
- `docs/ai/NOTEBOOKLM_PROJECT_BRIEF.md` - curated source brief for NotebookLM research
- `docs/ai/NOTEBOOKLM_WORKFLOW.md` - safe NotebookLM import and research workflow
- `.cursor/rules/*.mdc` - Cursor IDE project rules for scoped AI-agent context
- `docs/ARCHITECTURE.md` - runtime modules and data flow
- `quality/dosage_policy_transnistria.md` - numeric dosage source policy
- `AGENTS.md` - AI-agent guardrails for future autonomous work

For a quick local orientation before starting a new agent task:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/autopilot_context.ps1
```

To create a safe one-file source pack for NotebookLM:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_notebooklm_pack.ps1
```

## Security

- `.env`, local data, backups, caches, build output, and audit artifacts are ignored.
- GitHub secret scanning and push protection should stay enabled.
- Web sessions are HMAC-signed, time-limited, and bound to the authenticated Telegram ID.
- Web login/admin endpoints use Redis-backed rate limiting with safe in-process fallback when Redis is unavailable.
- Privacy deletion endpoints remove database records and raw uploaded files referenced by document metadata paths.
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
