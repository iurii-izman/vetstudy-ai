# NotebookLM Workflow For VetStudy AI

Last updated: 2026-05-03.

## Recommendation

Use NotebookLM as a curated research workspace, not as a direct write-capable integration.

For the current private beta, the best workflow is:

1. Create a NotebookLM notebook named `VetStudy AI - Product and Safety Research`.
2. Upload `docs/ai/NOTEBOOKLM_PROJECT_BRIEF.md`.
3. Add the safe project source files listed in that brief.
4. Ask NotebookLM to synthesize product, UX, safety, learning, and evaluation recommendations.
5. Bring the result back into `docs/ai/AUTOPILOT_NEXT_BLOCKS.md` as small implementation prompts.

## Why Not Direct MCP First

NotebookLM is primarily source-driven: you add documents, websites, Google files, copied text, YouTube links, and similar sources, then ask grounded questions over those sources.

Direct automation is not the right first move for this repo because:

- Consumer NotebookLM does not need repo write access.
- NotebookLM Enterprise has API support, but that is a Google Cloud/enterprise path, not a simple local private-beta dependency.
- Third-party NotebookLM MCP/CLI projects exist, but they are not a safety baseline for private project data.
- MCP tools can execute actions and should be reviewed, scoped, and approved before use.

## Safe Source Pack

Main source:

- `docs/ai/NOTEBOOKLM_PROJECT_BRIEF.md`

Core project sources:

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

Deep implementation sources:

- `quality/medical_golden_set_seed.json`
- `quality/evidence_sources/sources.json`
- `app/ai/safety.py`
- `app/ai/prompts.py`
- `scripts/quality_audit.py`
- selected tests under `app/tests/`

To generate one uploadable Markdown file:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_notebooklm_pack.ps1
```

For a larger implementation-oriented pack:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_notebooklm_pack.ps1 -Deep
```

The generated file is written under `artifacts/notebooklm/`, which is intentionally ignored by git.

## Do Not Upload

- `.env`
- real tokens, provider keys, passwords, owner tokens
- private Telegram IDs
- raw uploaded files
- local database files
- backups
- generated audit artifacts
- private Codex session logs
- real client or patient records
- proprietary veterinary formularies or textbook content without confirmed license rights

## Practical Use Cases

Use NotebookLM for:

- "Next 20 improvements" product research.
- User learning path design.
- Safety golden-set expansion ideas.
- Prompt contract critique.
- Case simulator rubric design.
- Evidence policy critique.
- Dashboard/cockpit information architecture.
- Turning research into 6-10 small PR prompts.

Do not use NotebookLM for:

- Direct clinical validation.
- Final dosage/source decisions.
- Copying copyrighted veterinary content.
- Editing repo files automatically.
- Managing secrets or deployment credentials.

## Import Options

Preferred simple path:

- Upload the Markdown files directly if your NotebookLM UI supports Markdown upload.

Google Drive path:

- Convert the main brief to a Google Doc.
- Add the Google Doc as a NotebookLM source.
- Re-import after major project changes because NotebookLM sources are snapshots/copies rather than a live repo mirror.

PDF path:

- Export `docs/ai/NOTEBOOKLM_PROJECT_BRIEF.md` to PDF and upload it.
- This is useful if layout stability matters, but Markdown is easier to maintain.

## Prompt Routine

Start with:

```text
Read the VetStudy AI sources. First summarize the product boundary, target user, safety constraints, and current roadmap. Then list the five biggest decision risks before suggesting new features.
```

Then use the specific prompts in `docs/ai/NOTEBOOKLM_PROJECT_BRIEF.md`.

## Bringing Results Back

When NotebookLM produces a useful answer:

1. Save the useful summary manually outside secrets-bearing files.
2. Ask Codex/Cursor to convert it into an implementation block.
3. Keep the block small and testable.
4. Update `docs/ai/AUTOPILOT_NEXT_BLOCKS.md` only after checking safety constraints.
5. Do not paste unsupported medical claims into product prompts.

## References

- NotebookLM source types and limits: https://support.google.com/notebooklm/answer/16215270
- NotebookLM Workspace privacy/source summary: https://workspace.google.com/products/notebooklm/
- NotebookLM Enterprise source API: https://docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/api-notebooks-sources
