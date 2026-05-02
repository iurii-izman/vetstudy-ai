# Closed Beta Decisions

Date: 2026-05-03.

Scope: private educational beta for one veterinary student. The service is for virtual practice, case reasoning, revision, notes, flashcards, and self-study. It is not for diagnosis or treatment decisions for real animals.

This document closes the practical decisions that do not need to block a one-person closed beta. Revisit every section before expanding beyond one trusted user.

## 1. Medical Validation Policy

Decision for closed beta:

- Use the tracked seed golden set in `quality/medical_golden_set_seed.json` as the baseline regression suite.
- Treat `review_status=seed` as engineering safety coverage, not expert veterinary approval.
- High-risk answers are allowed only as educational explanations with safety warnings, clarifying questions, or `needs manual check` language.
- No generated answer is considered a final clinical recommendation.

Closed for private beta:

- A reproducible seed golden set exists in the repository.
- `scripts/quality_audit.py` defaults to pipeline mode and uses `quality/medical_golden_set_seed.json`.

Still required before broader beta:

- Expert veterinarian review of golden set expectations and high-risk answer samples.

## 2. Veterinary Sources and Formularies

Decision for closed beta:

- Do not ingest proprietary formularies or paid veterinary books unless the project owner has an explicit license.
- Use only user-owned notes/files or public sources for early Evidence/RAG work.
- Dosing content should be marked as requiring verification against the current label/formulary.

Allowed source classes for private beta:

- Public veterinary education/manual pages.
- Public professional guidelines.
- User-owned lecture notes and documents.
- Official product labels and regulator pages where available.

Not allowed without manual licensing:

- Full copied tables from proprietary formularies.
- Paid textbook chapters.
- Scraped commercial veterinary reference content.

## 3. Legal / Safety Notice Draft

Use this notice in README, onboarding, or web UI when needed:

```text
VetStudy AI is an educational study assistant for veterinary learning and virtual case practice. It does not provide a veterinary-client-patient relationship, diagnosis, prescription, dosage authorization, or treatment plan for real animals. For real animals, emergencies, toxicology, drug dosing, anesthesia, surgery, or rapidly worsening signs, consult a licensed veterinarian or emergency clinic. AI output can be incomplete or wrong and must be checked against current labels, formularies, and clinical judgment.
```

Privacy notice draft for private beta:

```text
During the private beta, messages, generated answers, notes, flashcards, model-call metadata, and uploaded document text may be stored in the local VetStudy AI database for study continuity, search, export, and debugging. AI prompts may be sent to the configured LLM providers. Do not submit client personal data, identifying owner data, or sensitive real-patient records. The beta owner can export or delete account/topic data through the app, but raw uploaded files may also need local filesystem cleanup before public release.
```

Data retention decision for private beta:

- Keep local beta data until the end of the private beta unless the student requests deletion.
- Export useful study material before deleting.
- Before public beta, implement and test raw uploaded file deletion as part of privacy deletion.

## 4. Model Policy

Current private-beta model policy:

- Current Groq/OpenRouter configuration is acceptable only for educational beta usage.
- Low-risk educational explanations can use the fast/cheap configured model.
- Dosage, toxicology, emergency, anesthesia/sedation, serious clinical cases, and drug interactions are high-risk.
- High-risk answers must pass safety gate and post-generation validation.
- If a stronger high-risk model is not configured, the product should prefer clarification, warning, and manual-check framing over confident treatment instructions.
- No current model is approved as an autonomous clinical decision maker.

Provider notes checked during this review:

- Groq documents that certain API logs may be retained up to 30 days, with opt-out controls available in Data Controls settings. Source: [Groq Your Data](https://console.groq.com/docs/your-data).
- OpenRouter states that it does not train on customer data, provider-side retention can be disabled, and pricing is pass-through/no markup. Source: [OpenRouter Pricing / Privacy and Security](https://openrouter.ai/pricing).
- Gemini API pricing docs distinguish free/paid tiers and show whether data is used to improve products by tier/model. Source: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).
- OpenAI API data controls list API endpoint training status and retention; chat/responses show no training and 30-day abuse monitoring by default, with ZDR/MAM options for eligible customers. Source: [OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data).

Before public/commercial use:

- Re-check provider terms, data retention settings, regional availability, and pricing on the exact account and exact models used.

## 5. Secrets Policy

Closed for private beta:

- `.env` is ignored by git and Docker build context.
- `.env.example` contains placeholders only.
- `scripts/preflight_check.py --db --schema --provider` passed with secrets present.

Decision:

- Do not rotate keys during one-person local private beta unless exposure is suspected.
- Rotate all Telegram/LLM/web tokens before public beta, after choosing final deployment target.
- Never commit `.env`, provider keys, Telegram tokens, or owner password/token.

## 6. Deployment Policy

Decision for private beta:

- Use local Docker Compose + Telegram polling.
- Public domain, TLS, webhook, reverse proxy, and firewall hardening are not required for one-person local beta.
- If remote access is needed, use a proper VPS/PaaS deployment with HTTPS and webhook mode.

Closed for private beta:

- Docker Compose stack runs.
- Backend readiness works via `http://localhost:8000/ready` and inside container.
- Note: on this Windows/WSL/Docker setup, `http://127.0.0.1:8000/ready` may hit a different local listener and return 503; use `localhost` for local smoke unless the port conflict is resolved.

## 7. Backup / Restore

Closed during this review:

- A `pg_dump` custom-format backup of compose DB was restored into a separate temporary DB `vetstudy_restore_check`.
- Restored counts were readable for key tables: users, topics, messages, memory_items, model_calls.
- The temporary restore-check DB was removed after verification.

Decision:

- For local private beta, manual restore drill is sufficient.
- Before public beta, schedule automated backups and perform a restore drill on a separate production-like database.

## 8. Telegram Beta Smoke

Decision:

- Autopilot can document and test code paths, but only the project owner can complete real Telegram smoke because it requires the actual private group, bot permissions, and user account.

Required private-beta smoke:

1. `/start`
2. `/help`
3. `/create_default_topics` or `/bind_topic pharmacology`
4. Ask one low-risk educational question.
5. Ask one dosage question with missing data and verify clarification.
6. Ask one toxicology/red-flag question and verify escalation.
7. Use inline save/cards/quiz.
8. Run `/search`, `/review`, `/export`.
9. Upload one small TXT/MD document and check `/docs`.

## 9. Allowlist Policy

Closed for private beta:

- `ALLOWED_TELEGRAM_USER_IDS` is set and preflight passes.

Decision:

- For one-person beta, allowlist must contain exactly the student and owner/tester IDs required for the session.
- Do not run with an empty allowlist outside isolated local development.

Manual confirmation still required:

- The owner must confirm the actual Telegram IDs because the assistant should not print or expose them.

## 10. Commercial / Data Processing Terms

Decision for private beta:

- Treat this as non-commercial private educational testing.
- Do not input real client PII or identifiable patient records.
- Do not promise confidentiality beyond the configured provider terms and local storage behavior.

Closed enough for private beta:

- Provider docs were checked at a high level and linked above.

Before public/commercial use:

- Re-check exact provider account settings, DPA availability, data retention, regional processing, payment terms, and usage policy.

## 11. Product Decisions

Private beta product policy:

- Pricing: free/private, no billing.
- Billing plan: disabled; ignore billing fields except for future compatibility.
- Multi-user: disabled except owner/admin/testing needs.
- Target beta length: 1-2 weeks.
- Success criteria:
  - student can complete realistic virtual case practice;
  - no context leakage between topics/users;
  - high-risk prompts do not produce confident unsafe action;
  - useful cards/search/export;
  - negative feedback and failures are logged for triage.

No public launch until:

- high-risk golden set passes with acceptable thresholds;
- at least one expert or advanced reviewer checks representative samples;
- privacy/deletion behavior includes raw uploaded files;
- production deployment and backups are tested.

## 12. UX Testing

Decision for private beta:

- One student can act as the UX cohort.
- Feedback can be collected informally in Telegram or through future feedback buttons.

Minimum feedback questions:

- Which answers were useful?
- Which answers felt unsafe, vague, or wrong?
- Which commands were confusing?
- Did cards/search/review actually help study?
- Which topics should be added first?

## 13. Public Beta Go/No-Go

Decision:

- Public beta is explicitly not approved by this document.
- Private beta is approved if Telegram smoke passes and the student understands the educational-only limitation.

Go/no-go criteria for later:

- No critical safety failures in recent audit.
- Restore drill completed on production-like DB.
- Secrets rotated for deployment.
- Domain/TLS/webhook checked.
- Legal/privacy copy reviewed for the target audience.

## 14. Incident Monitoring and Triage

Private beta process:

- Review `error_events`, backend logs, negative feedback, and quality audit artifacts after each study session.
- For any high-risk unsafe answer: save prompt/answer, add it to golden set, adjust validator/safety/prompt, rerun tests.

Manual part:

- Human triage is still required because determining whether a veterinary answer is wrong or unsafe cannot be fully delegated.

## 15. Git / Release Hygiene

Closed during this review:

- The folder was not a git repository.
- A git repository was initialized.
- `.gitignore` and `.dockerignore` were tightened for `.ruff_cache/` and `*.egg-info/`.
- Initial commit created: `a131728 chore: initialize project repository`.
- `.env`, `artifacts/`, caches, `web/node_modules/`, `web/dist/`, and egg-info are ignored.

Still recommended:

- Push to a private remote repository.
- Use PRs for future changes.
- Add branch protection after remote setup.
- Consider `.gitattributes` for line-ending normalization.

## Remaining Manual-Only Actions

These are the only items that still genuinely require the project owner or a human expert:

1. Confirm the actual Telegram allowlist IDs without exposing them in chat/logs.
2. Run the real Telegram smoke in the private group with the actual bot permissions.
3. Decide whether to push this new git repository to GitHub/GitLab/etc. and create the private remote.
4. Rotate real Telegram/LLM/web secrets before any non-local or broader beta.
5. Choose and license any proprietary veterinary formularies or paid source material.
6. Have a veterinarian or advanced reviewer validate the golden set and representative high-risk answers before broader release.
7. Review provider terms on the actual accounts before public/commercial use.
8. Make the final public-beta go/no-go decision after private beta feedback.
