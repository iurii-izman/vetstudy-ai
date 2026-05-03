# Known Limitations (Beta)

This file is the explicit go/no-go risk list for `v0.1.0-beta.1`.

## 1. Educational Scope Only

VetStudy AI is not a clinical decision system. Any answer involving real animals, emergency care, toxicology, anesthesia/sedation, surgery, drug interactions, or dosing must be checked by a licensed veterinarian and current source material.

## 2. Medical Validation Is Seed-Level

The tracked golden set is an engineering regression suite, not expert approval. Before broader beta, representative high-risk answers and expected outputs need veterinary review.

## 3. Provider and Model Limits

Free-tier providers can rate limit, change model availability, or degrade latency. Keep `scripts/quality_audit.py --delay-s 6` for batch checks and re-check provider terms, retention, and pricing before non-local use.

## 4. Safety Gate Is Rule-Based

The safety gate and validators reduce obvious unsafe output, but they can miss rare phrasings or over-block benign study questions. Unsafe examples must be added to `quality/medical_golden_set_seed.json`.

## 5. Evidence Mode Is Curated, Not Comprehensive

Evidence source coverage is intentionally small for beta. Numeric dosing should use exact product labels/SPC or licensed formulary material and mark incomplete cases as `needs_manual_check`.

## 6. Web Cabinet Is Single-Owner First

The web cabinet is designed for owner/admin beta operations. Session tokens are bound to the authenticated Telegram ID, but multi-user web product flows are not a public launch surface yet.

## 7. Raw Uploaded Files Need Deployment Policy

Database export/delete endpoints cover application rows. Any raw uploaded files and infrastructure backups must be cleaned through the deployment runbook before public beta.

## 8. Frontend Dev Tooling Audit

`npm audit --omit=dev` should stay clean. Dev-server tooling findings in Vite/Vitest/esbuild should be handled by dependency updates and the dev server must stay local-only.

## 9. Analytics Are Beta-Quality

Product analytics cover activation, search, feedback, cards, review, and high-risk signals. Historical data before instrumentation is not backfilled.

## 10. Manual Beta Smoke Remains Required

Real Telegram group permissions, topic binding, bot admin rights, and student allowlist confirmation require the owner. Autopilot cannot complete those checks without the actual beta environment.
