# Runbook (Staging/Prod)

## 1. Pre-deploy checklist
- `python -m pytest -q`
- `python -m ruff check . --exclude web/node_modules --exclude web/dist --exclude artifacts`
- `python scripts/preflight_check.py --db --schema --provider`
- `alembic upgrade head` on target DB clone.
- For web changes: `cd web && npm test && npm run build && npm audit --omit=dev`.
- For `APP_ENV=prod`, verify embeddings config is complete: non-mock `LLM_EMBEDDINGS_PROVIDER`, non-empty `LLM_EMBEDDINGS_MODEL`, and matching provider API key (preflight fails otherwise).
- For `APP_ENV=prod`, run `python scripts/preflight_check.py --provider` to smoke-test both generation and embeddings; fail-fast if embeddings return empty vectors.

## 2. Deploy and verification
- Apply migrations first, then deploy app and worker.
- Keep media worker as a dedicated process/service; do not rely on bot polling process to start indexing workers.
- Verify `GET /health` and `GET /ready`.
- Verify media worker diagnostics: `python -m app.media.worker --diagnose` (and `--fail-on-stall` for non-zero on suspected queue stall).
- Verify `/api/web/auth/session` login and `/api/web/auth/refresh` rotation.
- Verify `WEB_OWNER_TELEGRAM_ID` is configured; owner login/session issuance rejects missing owner id and does not fallback to allowlist entries.
- Verify `/api/web/admin/metrics/providers` and `/api/web/admin/alerts/unanswered`.
- Verify nightly safety drift monitor: `python scripts/safety_drift_monitor.py --lookback-hours 24 --limit 500 --min-hits 2`; alerts are written to `error_events` with category `safety_drift_pattern_detected`.
- Verify `/api/web/admin/analytics/retrieval-quality` for retrieval hit/empty rates.
- Verify router logs include `route_decision` and `reason` fields (JSON logs, `docker compose logs bot`).
- Verify breaker transitions in logs (`event=breaker_state`, states `open|half_open|closed`) during provider instability.
- Verify web login/admin rate limits with Redis available; on Redis outage, limiter should gracefully fall back to in-process limiting (reduced cross-instance consistency).
- Verify privacy delete flows remove `documents` rows and raw upload files referenced in document metadata paths.

## 3. Backup/restore drill
- Backup: `./scripts/backup_pg.sh`.
- Restore to isolated DB:
  - `pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" ./backups/<dump>.dump`
- Validate row counts for `users/sessions/messages/model_calls/error_events`.
- Automated drill: `python scripts/restore_verify.py --database-url "$DATABASE_URL"` (isolated temporary restore-check container + key-table count validation).

## 4. Secret rotation
- Rotate: `WEB_OWNER_TOKEN`, `WEB_SESSION_SECRET`, provider keys, `USER_ID_HASH_SALT`.
- Prefer `WEB_OWNER_PASSWORD_HASH` over plain `WEB_OWNER_PASSWORD`.
- If `WEB_OWNER_PASSWORD_HASH` has `$`, keep it single-quoted in `.env` to avoid Compose interpolation warnings.
- After rotation run one login smoke and one Telegram request smoke.

## 5. Localhost / 127.0.0.1 caveat (Windows/WSL/Docker)
- On Windows+WSL, `localhost:8000` and `127.0.0.1:8000` may hit different listeners.
- Use the same host consistently in browser/proxy checks.
- If one address returns `503` while another is healthy, verify Docker port bindings and WSL forwarding first.

## 6. Rollback plan
- Keep previous image tag.
- Rollback order:
  - switch deployment to previous image;
  - if migration is backward compatible, keep DB head;
  - if not backward compatible, restore latest verified backup.
- Re-check `/ready`, Telegram webhook, worker queue consumption, and admin error feed.

## 7. Web dashboard address check
- Repository default addresses:
  - backend/API: `http://localhost:8000`
  - frontend dev server: `http://localhost:5173`
- `http://localhost:1455` is not used by this project unless overridden externally.

## 8. Docker project isolation and hygiene
- Compose stack name is fixed as `vetstudy` (`name: vetstudy` in `docker-compose.yml`), so containers/network/volumes stay isolated from other projects.
- App services (`backend`, `bot`, `media-worker`) share one runtime image: `vetstudy/app:local`; this avoids duplicate per-service images.
- Service labels are set for filtering/monitoring:
  - `com.vetstudy.project=vetstudy`
  - `com.vetstudy.stack=beta`
  - `com.vetstudy.role=<service>`
- Useful monitoring commands:
  - `docker compose ps`
  - `docker compose logs bot --tail=300`
  - `docker ps --filter label=com.vetstudy.project=vetstudy`
  - `docker stats $(docker ps -q --filter label=com.vetstudy.project=vetstudy)`
- Safe cleanup workflow (do not touch named project volumes unless you want data loss):
  - audit first: `docker system df -v`
  - remove unused images only: `docker image prune -a`
  - remove unused build cache: `docker builder prune -a`
  - remove unused anonymous volumes only: `docker volume prune`
