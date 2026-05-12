# Release Checklist (GitHub)

- Run `python scripts/quality_audit.py --limit 10 --delay-s 0 --fail-on-regression --min-overall-quality 62 --max-generic-rate 0.35 --min-clarification-hit-rate 0.8` in pipeline mode and verify `safety_allowed`, `safety_action`, `validator_flags`, and quality metrics are present in `artifacts/quality_audit/quality_audit_latest.json`.
- Verify nightly workflow `Nightly Quality Audit` succeeds on the full current golden set and uploads `artifacts/quality_audit/*` artifacts.

1. Sync and verify branch
- Ensure branch is up to date with `main`.
- Confirm no accidental secrets in tracked files.

2. Validate locally
- `pytest -q`
- `alembic upgrade head` against a clean DB.
- `python scripts/preflight_check.py --db --schema --provider`
- `python scripts/quality_audit.py --limit 10 --delay-s 0 --fail-on-regression --min-overall-quality 62 --max-generic-rate 0.35 --min-clarification-hit-rate 0.8`
- Smoke test Telegram flow with `LLM_PRIMARY_PROVIDER=mock`.

Quality degradation definition for release gate:
- lower aggregate clinical specificity/actionability (`overall_quality` below threshold);
- increased generic-answer share (`generic_rate` above threshold);
- missing explicit clarifying questions for `requires_clarification` cases (`clarification_hit_rate` below threshold).

3. AI config validation
- Verify `.env.example` includes all LLM router variables.
- Validate at least one production provider key is set in deployment secrets.
- Confirm fallback provider/model configured.
- For `APP_ENV=prod`, confirm embeddings preflight requirements: non-mock provider, model set, matching provider key.
- Confirm `WEB_OWNER_TELEGRAM_ID` is explicitly set (owner session issuance rejects missing owner id; no allowlist fallback).

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
- Run `python scripts/restore_verify.py --database-url "$DATABASE_URL"` and keep output in release notes.
