# VetStudy AI NotebookLM Research Brief

Last updated: 2026-05-03.

Use this document as the main source for a NotebookLM notebook named `VetStudy AI - Product and Safety Research`.

This brief is intentionally safe to upload: it contains no real tokens, private Telegram IDs, raw clinical records, raw uploads, backups, or provider secrets. Keep it that way.

## 1. Project Snapshot

VetStudy AI is a private-beta, Telegram-first veterinary study assistant. It is built for one trusted Russian-speaking veterinary specialist who has a veterinary diploma and permission to practice, but returned after about 5 years away from practical work.

The product goal is not to replace a clinician. The goal is to help the user re-enter practical veterinary thinking through safe explanations, virtual cases, study cards, memory/search, document notes, and feedback loops.

Primary interface:

- Telegram bot in a private supergroup with forum topics.
- Inline actions for save, cards, quiz, review, feedback, search, and export.

Operator interface:

- FastAPI + React/Vite web cabinet for owner/admin visibility.
- Analytics, feedback, source coverage, errors, memory, notes, cards, and topics.

Runtime stack:

- Python 3.12, FastAPI, aiogram.
- PostgreSQL with pgvector-ready schema.
- Redis Streams for document indexing jobs.
- Alembic migrations.
- React/Vite owner cabinet.
- Docker Compose local private-beta deployment.

Repository:

- Local path: `C:\Dev\pollychat`.
- GitHub remote: `git@github.com:iurii-izman/vetstudy-ai.git`.
- Release line: `v0.1.0-beta.1`.

## 2. User Profile And UX Target

The current user is one veterinary specialist:

- Has university veterinary education and diploma.
- Can legally practice.
- University marks were around "good" on average.
- Had a long break of about 5 years after university because of maternity leave.
- Practical experience is limited.
- Theory is partially forgotten.
- Needs confidence, structure, repetition, and a practical bridge from university knowledge to clinic workflow.

The target answer style:

- Friendly and calm, not patronizing.
- Practical and memorable, not dry theory.
- Accurate enough for safe learning, but honest about uncertainty.
- Telegram-readable on a phone.
- Answers should teach while answering.

Preferred educational answer shape:

1. Short answer.
2. Clinical logic.
3. What to do in practice or in a virtual case.
4. Common mistakes.
5. How to remember it.
6. One small self-check question.

High-risk content must still preserve strict safety boundaries.

## 3. Product Boundary

VetStudy AI is educational beta software only.

It must not:

- Create a veterinarian-client-patient relationship.
- Diagnose a real animal.
- Prescribe medication.
- Authorize dosage.
- Provide a real treatment plan.
- Hide uncertainty behind confident wording.

It may:

- Explain concepts.
- Train virtual case reasoning.
- Help structure study.
- Ask for missing case data.
- Mark high-risk items as `needs_manual_check`.
- Help generate safe study cards when source and safety constraints allow it.

## 4. Current Architecture

Telegram flow:

```text
Telegram user/group
  -> aiogram handlers
  -> safety gate + topic/session context
  -> LLM router + validators
  -> Postgres memory/messages/cards/feedback
  -> Telegram response + inline actions
```

Web flow:

```text
Web cabinet
  -> FastAPI /api/web
  -> signed bearer/session auth
  -> Postgres analytics/admin/user data
```

Document flow:

```text
Document upload
  -> stored file metadata
  -> Redis Stream job
  -> media worker
  -> extracted chunks + embeddings-ready rows
```

Key modules:

- `app/main.py`: FastAPI app, health/readiness, webhook, lifespan.
- `app/telegram/handlers.py`: Telegram commands, text flow, callbacks, media entrypoints.
- `app/ai/`: prompt manager, router, provider adapters, safety/validation.
- `app/db/`: SQLAlchemy models, sessions, repositories.
- `app/media/`: extractors, storage, Redis stream jobs, worker.
- `app/learning/`: flashcard and review behavior.
- `app/evidence/`: source-aware answer wrapping and high-risk evidence status.
- `app/analytics/`: beta product analytics and funnel reporting.
- `app/web/`: web API and session security.
- `web/`: React/Vite owner cabinet.

## 5. Current Strengths

- The project is no longer a prototype-only bot: it has migrations, tests, docs, CI, deployment notes, auth, quotas, callbacks, analytics, and backup/recovery notes.
- Telegram inline buttons perform real actions.
- User-scoped memory, cards, search, and web session binding are covered by tests.
- High-risk answers are wrapped by safety and evidence concepts.
- Operational docs exist for private beta, release, backup, restore, Windows self-heal, and local recovery.
- There is a current autopilot handoff and ordered AI development block list.

## 6. Known Gaps

These are the current highest-risk or highest-ROI gaps:

- `scripts/quality_audit.py` records results but still needs stronger CI-failing checks for expectations like `must_include`, `must_not_include`, `requires_escalation`, `requires_clarification`, and expected risk tags.
- `SafetyGate` is rule-based and can miss Russian morphology or realistic phrasing. Known misses from the 2026-05-03 audit include `дозу`, `судорогах`, `съела шоколад`, and `ХБП` in some interaction contexts.
- Evidence mode is curated and source-aware, not comprehensive clinical verification.
- Raw uploaded file deletion is still a privacy-hardening item before broader beta.
- Free provider availability, model quality, retention, and pricing must be rechecked before public/commercial use.
- Medical accuracy still needs human veterinary review before expansion beyond private beta.
- Telegram smoke in the real private group still requires the owner and actual bot permissions.

## 7. Safety And Dosage Policy

Numeric dosage answers are high-risk.

For Transnistria private beta, use a Moldova-first regional check:

1. Check exact product or active substance in the ANSA Moldova veterinary medicinal product register.
2. If ANSA references EMA/EU sources or the product is EU/EMA-authorized, verify official product information/SPC.
3. If the exact local label/package leaflet is available from the owner/student, prefer that label.
4. If only a generic active substance is known, ask for exact trade name, concentration, pharmaceutical form, target species, and indication.

Do not calculate a numeric dose unless the case includes:

- Species.
- Body weight.
- Age/life stage and pregnancy/lactation status when relevant.
- Indication or suspected diagnosis.
- Exact drug, trade name when available, formulation and concentration.
- Route and dosing interval requested or supported by source.
- Relevant comorbidities, especially renal/hepatic disease, dehydration, GI ulcer risk, seizures, cardiac disease.
- Current medicines/supplements and recent NSAID/steroid/anticoagulant exposure.

High-risk categories require stronger support or `needs_manual_check`:

- Cats and NSAIDs.
- Aminoglycosides.
- Anticoagulants.
- Sedatives/anesthetics.
- Opioids.
- Toxicology and antidotes.
- Renal/hepatic impairment.
- Food-producing animals and withdrawal periods.
- Off-label/extralabel use.
- Compounding or human medicines used in animals.

## 8. Current Autopilot Roadmap

The next ordered implementation blocks are:

1. Safety Gate v2 + Strict Quality Audit.
2. Teaching Answer Format v2.
3. Daily Learning Route.
4. Cards And Quiz 2.0.
5. Case Simulator MVP.
6. Web Learning Cockpit + Feedback Loop.

Block 1 should happen before broad user-facing learning expansion because audit already found safety misses in realistic phrasing.

## 9. Research Tracks For NotebookLM

Use NotebookLM to explore and synthesize better decisions in these tracks.

### Track A: Return-To-Practice Learning Path

Goal: design a humane path from university knowledge after a 5-year break into practical veterinary workflow.

Questions:

- What should a first 2-week, 4-week, and 8-week study plan look like for a returning small-animal veterinarian?
- Which topics create the biggest practical confidence gains early?
- How should virtual cases be sequenced from easy to hard?
- How can the assistant reduce shame/anxiety while still being precise?
- What answer patterns make learning stick without turning every answer into a lecture?

### Track B: Practical Clinical Reasoning UX

Goal: make answers teach clinical thinking.

Questions:

- What is the best response structure for a Telegram veterinary study assistant?
- How should the bot separate triage, missing data, differentials, diagnostics, treatment discussion, and owner explanation?
- Which information should always be asked before discussing medication, toxicology, emergency signs, anesthesia, or interactions?
- What are good "common mistake" and "memory hook" patterns?

### Track C: Safety Gate And Evaluation

Goal: catch unsafe or overconfident output before and after generation.

Questions:

- What categories should a veterinary educational safety gate detect?
- How should Russian-language morphology, abbreviations, and colloquial phrasing be handled?
- What should be in a golden set for veterinary safety regression testing?
- How should `quality_audit.py` score answers and fail CI?
- What is the minimum acceptable behavior for toxicology, seizures, dyspnea, NSAIDs in cats, renal disease, and drug interactions?

### Track D: Evidence And Source Handling

Goal: improve source-backed answers without importing illegal or proprietary content.

Questions:

- What source hierarchy should be used for veterinary dosage and drug interactions in Moldova/Transnistria?
- How should product labels, ANSA, EMA/EU, public guidelines, user-owned notes, and licensed formularies be ranked?
- How should the assistant communicate "source not sufficient" without frustrating the user?
- What should be stored in an evidence source registry?
- What should be manually reviewed before public beta?

### Track E: Learning Cards, Quiz, And Review

Goal: make spaced repetition clinically useful.

Questions:

- Which card types are best for veterinary clinical reasoning: fact, cloze, next step, risk check, owner explanation?
- How can cards avoid memorizing unsafe medication instructions?
- What should a "leech" card workflow look like?
- How should quiz explanations explain why distractors are dangerous or less appropriate?
- How should due cards connect to daily practice cases?

### Track F: Case Simulator

Goal: train practical thinking through safe virtual cases.

Questions:

- What is the MVP flow for a virtual veterinary case simulator in Telegram?
- How should the bot evaluate user answers by rubric?
- What starter cases are safest and most useful for a returning practitioner?
- How should feedback identify unsafe assumptions without discouraging the user?
- What analytics should be logged for case learning?

### Track G: Web Cabinet And Feedback Loop

Goal: help the owner quickly see what needs improvement.

Questions:

- Which dashboard panels best reveal study gaps and safety risks?
- How should negative feedback, high-risk prompts, weak topics, due cards, source gaps, and search misses be triaged?
- What owner actions should exist from each dashboard item?
- What should stay hidden or redacted in the UI?

### Track H: Private Beta Operations

Goal: keep the one-person beta stable and safe.

Questions:

- What should the operator review after each study session?
- What should block moving from private beta to broader beta?
- Which provider/model terms must be rechecked before public use?
- How should raw upload deletion and backup retention be handled?
- What incidents should trigger adding a golden-set case?

## 10. High-Value NotebookLM Prompts

Paste these prompts into NotebookLM after adding the sources.

### Prompt 1: Next 20 Product Improvements

```text
Based only on the uploaded VetStudy AI sources, produce the next 20 highest-ROI project improvements.

Prioritize user comfort, practical learning, safe veterinary reasoning, and the return-to-practice path for the described user profile.

For each improvement include:
- user problem;
- proposed feature or behavior;
- why it matters;
- implementation area;
- safety risk;
- suggested acceptance test.

Do not suggest features that turn the product into a clinical decision system or prescription tool.
```

### Prompt 2: Daily Study Path

```text
Design a 14-day daily learning route for the target user.

Each day should fit 15-30 minutes and include:
- one mini-case;
- one practical concept;
- one medication/safety risk or "what to check before treatment" item;
- 3 review-card ideas;
- one reflection question;
- one confidence-building note.

Keep it practical for small-animal clinical work and educational-only.
```

### Prompt 3: Safety Golden Set Expansion

```text
Create 40 Russian-language safety regression prompts for VetStudy AI.

Cover emergency signs, toxicology, dosage, drug interactions, renal/hepatic disease, cats and NSAIDs, seizures, dyspnea, pregnancy/lactation, pediatric/geriatric animals, and owner-pressure phrasing.

For each prompt include:
- expected risk tags;
- whether clarification is required;
- whether escalation/triage language is required;
- must-include phrases;
- must-not-include behavior.
```

### Prompt 4: Answer Format Critique

```text
Using the project goals and user profile, critique the proposed educational answer structure:
"short answer -> clinical logic -> what to do in practice -> common mistakes -> how to remember -> mini self-check".

What should be changed for Telegram readability, safety, emotional comfort, and practical learning?
Return a revised answer contract with examples.
```

### Prompt 5: Case Simulator MVP

```text
Draft a safe MVP spec for the Telegram virtual case simulator.

Include:
- commands and inline actions;
- state model;
- 10 starter cases;
- feedback rubric;
- safety boundaries;
- analytics events;
- tests;
- what must be manually reviewed before broader beta.
```

### Prompt 6: Evidence Policy Review

```text
Review the evidence and dosage policy in the sources.

Find gaps, contradictions, and operational risks.
Suggest a source hierarchy and answer behavior for:
- exact product label available;
- generic active substance only;
- user asks for a dose with missing weight;
- cat NSAID question;
- aminoglycoside with kidney disease;
- toxicology question.
```

### Prompt 7: Web Cabinet Cockpit

```text
Design the web cabinet as a learning and safety cockpit, not a raw admin panel.

List the dashboard sections, the exact signals each section should show, what action the owner should take, and which data must be redacted or hidden.
```

### Prompt 8: Implementation Blocks

```text
Turn the best ideas into 6 small auditable PR blocks for a coding agent.

For each block include:
- scope;
- files likely touched;
- tests;
- acceptance criteria;
- model/reasoning recommendation;
- risks and rollback notes.
```

## 11. Suggested Sources To Add To NotebookLM

Add these project files as sources:

- `README.md`
- `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/beta/CLOSED_BETA_DECISIONS.md`
- `docs/beta/KNOWN_LIMITATIONS.md`
- `docs/beta/RUNBOOK.md`
- `docs/beta/RELEASE_CHECKLIST.md`
- `quality/dosage_policy_transnistria.md`
- `docs/ai/AUTOPILOT_HANDOFF.md`
- `docs/ai/AUTOPILOT_NEXT_BLOCKS.md`
- `docs/ai/CURSOR_MCP_SETUP.md`
- `docs/ai/NOTEBOOKLM_PROJECT_BRIEF.md`

Optional source files for deeper implementation research:

- `docs/ai/VetStudyAI_FINAL_SPEC.md`
- `docs/ai/VetStudyAI_AUTOPILOT_PROMPTS.md`
- `quality/medical_golden_set_seed.json`
- `quality/evidence_sources/sources.json`
- `app/ai/safety.py`
- `app/ai/prompts.py`
- `scripts/quality_audit.py`
- `app/tests/test_safety_gate.py`
- `app/tests/test_quality_audit_pipeline.py`
- `app/tests/test_prompt_manager.py`
- `app/tests/test_learning_service.py`

Do not add:

- `.env`
- provider keys
- Telegram tokens or IDs
- raw uploaded files
- backups
- local database files
- generated audit artifacts
- private Codex session logs
- real clinical records or client personal data

## 12. Suggested External Sources To Research Separately

Use NotebookLM Deep Research or manual web sources for these topics, then add only relevant, public, licensed, or official sources:

- Veterinary emergency triage education for small animals.
- Public veterinary toxicology guidance.
- Official product labels/SPC for region-relevant medicines.
- ANSA Moldova veterinary medicinal product register.
- EMA/EU veterinary product information pages.
- Spaced repetition and retrieval practice evidence.
- Clinical reasoning teaching methods.
- Deliberate practice and feedback rubrics for medical/veterinary education.
- Telegram bot UX patterns for learning tools.
- Private beta safety, privacy, and incident triage checklists.

Avoid uploading copyrighted veterinary formularies, textbook chapters, or scraped commercial reference content unless license rights are confirmed.

## 13. How To Use NotebookLM Output Back In The Repo

NotebookLM should be treated as a research synthesizer, not a code-changing tool.

Good output to bring back:

- Ranked feature lists.
- PR block proposals.
- UX critique.
- Safety golden-set ideas.
- Evidence-policy critique.
- Case simulator rubrics.
- Daily learning route drafts.

Before implementation:

- Convert suggestions into small PR prompts in `docs/ai/AUTOPILOT_NEXT_BLOCKS.md`.
- Check against `AGENTS.md` hard rules.
- Add tests for safety, privacy, prompt, validator, router, migration, or learning behavior.
- Do not copy unsupported veterinary claims directly into product prompts.
- Do not copy external source text wholesale into the repo.

