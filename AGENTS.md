# AI Agent Guide

This repository is a private-beta veterinary study assistant. Optimize for safe, small, auditable changes.

## Read First

- `README.md` for the product surface and commands.
- `docs/ARCHITECTURE.md` for module boundaries and data flow.
- `docs/beta/RUNBOOK.md` for deploy and recovery.
- `docs/beta/RELEASE_CHECKLIST.md` before release work.
- `docs/beta/CLOSED_BETA_DECISIONS.md` for product, privacy, provider, and medical-safety decisions.
- `quality/dosage_policy_transnistria.md` for numeric dose handling.

## Hard Rules

- Do not commit `.env`, real tokens, raw backups, local DB data, generated audit artifacts, or private Telegram IDs.
- Do not remove safety disclaimers, allowlist checks, quota checks, or user isolation tests.
- Do not add proprietary veterinary formulary/textbook content unless the repository owner confirms license rights.
- High-risk veterinary answers must ask for missing patient/source data or mark `needs_manual_check`; never turn beta output into a prescription.

## Change Discipline

- Prefer focused PRs tied to one issue.
- Keep schema changes in Alembic migrations and update model tests.
- Update README/runbook/checklists when deployment, env, or operational behavior changes.
- Add or update tests for security, privacy, quota, prompt, validator, router, or migration behavior.

## Checks

Run the narrowest checks during development and the full release set before publishing:

```bash
python -m ruff check .
python -m pytest -q
alembic upgrade head
cd web && npm ci && npm test && npm run build
```
