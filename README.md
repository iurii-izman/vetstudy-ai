# VetStudy AI

Production-ready backend for Telegram-first VetStudy AI.

## Stack
- FastAPI + aiogram
- PostgreSQL (+pgvector)
- Redis (required for durable document indexing jobs)
- Alembic migrations

## Quick start (new server)
1. Clone repo.
2. Copy env file:
```bash
cp .env.example .env
```
3. Fill required secrets in `.env`.
4. Start local stack:
```bash
docker compose up --build
```
5. Verify:
- `GET /health` -> `200 {"status":"ok"}`
- `GET /ready` -> `200` when DB and Redis are ready.

For free beta provider setup see `FREE_API_SETUP.md`.

## Docker
### Production Dockerfile
- Multi-stage build.
- Non-root runtime user.
- Built-in healthcheck.
- Runs migrations before API startup.

### Local dev compose
`docker-compose.yml` starts:
- `backend`
- `bot`
- `media-worker`
- `postgres`
- `redis`

Backend healthcheck uses `/ready`.
Redis is started with AOF persistence and a named volume so queued document jobs survive API/container restarts.

## Health checks
- `/health`: liveness
- `/ready`: readiness with dependencies
  - DB: mandatory (`SELECT 1`)
  - Redis: mandatory when `REDIS_URL` is set

## Document indexing queue
Document uploads are recorded as `queued` in the user's document list, then serialized into a Redis Streams queue (`media:document_index_jobs` by default). The `media-worker` process consumes that stream and preserves the existing status contract:
- success: `queued -> indexed`
- failure: `queued -> failed` with a `document_index_failed` `ErrorEvent`

The worker acknowledges a Redis message only after the document is marked `indexed` or `failed`. Jobs may be delivered more than once after a worker crash, so every document entry has a `job_id`; already completed jobs are skipped on retry.

Run a worker outside Docker with:
```bash
python -m app.media.worker
```

## Structured logging
JSON logs include:
- `request_id`
- safe telegram user id hash (`telegram_user_id`)
- `provider` / `model`
- `latency_ms`
- `error_category`

Stack traces are logged only server-side (`exc_info`) and never returned to user.

## Error handling
- API returns user-safe messages.
- Unexpected exceptions return generic `500` message.
- Telegram pipeline catches DB and runtime errors and sends safe replies without crashing the process.

## Backup and restore
### Backup script
```bash
export DATABASE_URL='postgresql://...'
./scripts/backup_pg.sh
```
Creates `./backups/vetstudy_YYYYmmdd_HHMMSS.dump`.

### Restore
```bash
pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" ./backups/<file>.dump
```

### Scheduled backups (cron)
Example daily backup at 03:30:
```cron
30 3 * * * cd /opt/vetstudy && DATABASE_URL='postgresql://...' BACKUP_DIR='/opt/vetstudy/backups' ./scripts/backup_pg.sh >> /var/log/vetstudy-backup.log 2>&1
```

## Deployment
### VPS (Docker)
1. Provision server with Docker + Compose plugin.
2. Put `.env` on server (do not commit).
3. Run:
```bash
docker compose pull || true
docker compose up -d --build
```
4. Put reverse proxy (Nginx/Caddy) with TLS in front of `:8000`.
5. For Telegram webhook set:
- `TELEGRAM_MODE=webhook`
- `WEBHOOK_URL=https://your-domain`
- `WEBHOOK_PATH=/telegram/webhook`

### Railway / Render / Fly.io
- Build from `Dockerfile`.
- Set all required env vars from section below.
- Ensure persistent Postgres is attached.
- Run command:
```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```
- Run a separate worker process:
```bash
python -m app.media.worker
```
- Healthcheck path: `/ready`.

### Supabase DB
Use Supabase Postgres connection string in `DATABASE_URL`, for example:
```env
DATABASE_URL=postgresql+psycopg://postgres:<password>@<host>:5432/postgres?sslmode=require
```
Then run migrations (`alembic upgrade head`) on deploy.

## Secrets policy
- `.env` is ignored by git.
- Keep real secrets only in runtime environment.
- Rotate API keys if accidentally exposed.

## CI
GitHub Actions runs:
- `ruff check app`
- `alembic upgrade head` (migration check against Postgres service)
- `pytest -q`
- frontend tests/build

## Beta preflight
Run before opening beta:
```bash
python scripts/preflight_check.py --db --schema --provider
python scripts/quality_audit.py
```
The quality audit writes JSON/Markdown artifacts under `artifacts/quality_audit/` for manual medical review.
Default `quality_audit` mode now runs the runtime safety/prompt/router/validator pipeline; use `--direct-prompt` only for legacy comparison.

## Required secrets/env for production
- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`
- `USER_ID_HASH_SALT`
- `WEB_OWNER_TELEGRAM_ID`
- `WEB_OWNER_PASSWORD`
- `WEB_OWNER_TOKEN`
- provider key based on selected provider:
  - `OPENAI_API_KEY` or
  - `OPENROUTER_API_KEY` or
  - `GROQ_API_KEY` or
  - `GEMINI_API_KEY`

## Recommended production env
- `APP_ENV=prod`
- `DEBUG=false`
- `TELEGRAM_MODE=webhook`
- `WEBHOOK_URL=https://<your-domain>`
- `REDIS_URL=redis://...`
- `MEDIA_JOBS_STREAM=media:document_index_jobs`
- `MEDIA_JOBS_GROUP=media-indexers`
- `ALLOWED_TELEGRAM_USER_IDS=<comma-separated ids>`
