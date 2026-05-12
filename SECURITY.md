# Security Policy

## Supported Version

The supported beta line is `v0.1.x-beta`. Security fixes should land on `main` and be released as a new beta tag.

## Reporting

Do not open public issues with secrets, tokens, private Telegram IDs, clinical records, or exploitable details.
Report privately to the repository owner first, then create a sanitized GitHub issue once sensitive details are removed.

## Secrets

- `.env` is ignored and must never be committed.
- Rotate `TELEGRAM_BOT_TOKEN`, LLM provider keys, `WEB_OWNER_TOKEN`, `WEB_SESSION_SECRET`, and `USER_ID_HASH_SALT` after any suspected exposure.
- Prefer `WEB_OWNER_PASSWORD_HASH` over a plain `WEB_OWNER_PASSWORD` in deployed environments.
- GitHub secret scanning and push protection should remain enabled.

## Data Handling

VetStudy AI is an educational beta assistant. Do not submit client personal data, owner identifying data, or sensitive real-patient records.
Privacy deletion endpoints now remove database records and referenced raw uploaded files (by `documents.metadata.stored_path`/path fields) in an idempotent way.
Exports cover application data only; infrastructure backups still require separate operational deletion/retention handling in runbooks.
