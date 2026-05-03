# Release Checklist (GitHub)

- Run `python scripts/quality_audit.py --limit 10` in pipeline mode (default) and verify `safety_allowed`, `safety_action`, and `validator_flags` are present in `artifacts/quality_audit/quality_audit_latest.json`.

1. Sync and verify branch
- Ensure branch is up to date with `main`.
- Confirm no accidental secrets in tracked files.

2. Validate locally
- `pytest -q`
- `alembic upgrade head` against a clean DB.
- `python scripts/preflight_check.py --db --schema --provider`
- `python scripts/quality_audit.py --delay-s 6`
- Smoke test Telegram flow with `LLM_PRIMARY_PROVIDER=mock`.

3. AI config validation
- Verify `.env.example` includes all LLM router variables.
- Validate at least one production provider key is set in deployment secrets.
- Confirm fallback provider/model configured.

4. Observability and cost safety
- Confirm `model_calls` rows are being written for each AI request.
- Confirm daily/monthly limits and max request tokens are configured.
- Review logs for `ai_call` structured entries.
- If `SENTRY_DSN` is enabled, verify one captured test exception in Sentry.
- Check `/api/web/admin/metrics/providers` and `/api/web/admin/alerts/unanswered`.

5. GitHub release hygiene
- Open PR with summary of AI/router changes and migration notes after the beta baseline is published.
- Ensure CI is green.
- Ensure Dependency Review and CodeQL are enabled for future PRs.
- Confirm branch protection/ruleset on `main` after first push.
- Tag beta release (e.g. `v0.1.0-beta.1`) after validation.

6. Post-release checks
- Verify `/health` endpoint.
- Send one Telegram test prompt and verify fallback behavior by disabling primary key.
- Validate session auth flow: `/api/web/auth/session` + `/api/web/auth/refresh`.
- Follow `docs/beta/RUNBOOK.md` for backup restore drill and rollback rehearsal.
