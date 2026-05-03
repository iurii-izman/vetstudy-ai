# Contributing

VetStudy AI is in private beta. Keep changes small, reviewed, and traceable.

## Workflow

1. Open or reference a GitHub issue before larger work.
2. Use a feature branch from `main`.
3. Keep PRs focused on one product or engineering outcome.
4. Include tests for behavior changes and migrations for schema changes.
5. Update docs when runtime, safety, data, or release behavior changes.

## Local Checks

```bash
python -m ruff check .
python -m pytest -q
alembic upgrade head
cd web && npm ci && npm test && npm run build
```

For beta readiness:

```bash
python scripts/preflight_check.py --db --schema --provider
python scripts/quality_audit.py
```

## Safety Rules

- Never commit `.env`, provider keys, Telegram tokens, database dumps, backups, or generated audit artifacts.
- Do not add proprietary veterinary source content unless licensing is explicit.
- Treat dosage, toxicology, anesthesia/sedation, emergencies, and interactions as high-risk educational content.
- Any unsafe high-risk output should become a regression case in `quality/medical_golden_set_seed.json`.
