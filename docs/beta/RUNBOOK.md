# Runbook (Staging/Prod)

## 1. Pre-deploy checklist
- `python -m pytest -q`
- `python -m ruff check . --exclude web/node_modules --exclude web/dist --exclude artifacts`
- `python scripts/preflight_check.py --db --schema --provider`
- `alembic upgrade head` on target DB clone.
- For web changes: `cd web && npm test && npm run build && npm audit --omit=dev`.

## 2. Deploy and verification
- Apply migrations first, then deploy app and worker.
- Verify `GET /health` and `GET /ready`.
- Verify `/api/web/auth/session` login and `/api/web/auth/refresh` rotation.
- Verify `/api/web/admin/metrics/providers` and `/api/web/admin/alerts/unanswered`.

## 3. Backup/restore drill
- Backup: `./scripts/backup_pg.sh`.
- Restore to isolated DB:
  - `pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" ./backups/<dump>.dump`
- Validate row counts for `users/sessions/messages/model_calls/error_events`.

## 4. Secret rotation
- Rotate: `WEB_OWNER_TOKEN`, `WEB_SESSION_SECRET`, provider keys, `USER_ID_HASH_SALT`.
- Prefer `WEB_OWNER_PASSWORD_HASH` over plain `WEB_OWNER_PASSWORD`.
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
