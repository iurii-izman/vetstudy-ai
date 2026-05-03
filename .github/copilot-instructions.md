Follow `AGENTS.md`, then read `docs/ai/AUTOPILOT_HANDOFF.md` and `docs/ai/AUTOPILOT_NEXT_BLOCKS.md` before planning new work.
If working in Cursor or changing IDE automation, also read `docs/ai/CURSOR_MCP_SETUP.md` and `.cursor/rules/*.mdc`.

Keep changes small, safety-preserving, and release-aware.

Never introduce real secrets, private Telegram IDs, clinical records, generated audit artifacts, or proprietary veterinary source content.
For high-risk veterinary content, preserve the educational-only scope and `needs_manual_check` behavior.
