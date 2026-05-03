# Cursor IDE And MCP Setup

Last updated: 2026-05-03.

This project now has Cursor project rules under `.cursor/rules/*.mdc`. They are the first, safest upgrade for IDE autopilot because they give the agent persistent project memory without granting new external tool permissions.

## What Cursor Should Load

- `.cursor/rules/000-project-overview.mdc` is always-on and keeps the project guardrails, model defaults, and start routine in context.
- `010-veterinary-safety.mdc` attaches to safety, prompt, validator, audit, and dosage-policy files.
- `020-backend-architecture.mdc` attaches to Python backend, scripts, migrations, and dependency files.
- `030-telegram-learning-ux.mdc` attaches to Telegram, learning, memory, and prompt work.
- `040-web-cabinet.mdc` attaches to the React/Vite web cabinet.
- `050-ops-release.mdc` attaches to deployment, CI, release, and beta docs.
- `060-cursor-mcp-tooling.mdc` attaches when editing Cursor, MCP, or autopilot handoff files.

Cursor's current project-rules system stores rules in `.cursor/rules`, uses `.mdc` files with metadata such as `description`, `globs`, and `alwaysApply`, and still supports but deprecates root `.cursorrules`.

## Recommended Cursor Workflow

1. Open Cursor at `C:\Dev\pollychat`, not a parent folder.
2. Start a new agent task with: "Follow project rules, read `AGENTS.md`, then run `scripts/autopilot_context.ps1` before planning."
3. Give the agent one block from `docs/ai/AUTOPILOT_NEXT_BLOCKS.md`.
4. For code changes, ask for a small auditable PR scope and the narrow checks from the relevant rule.
5. For safety or prompt work, require tests before accepting the change.

## MCP Recommendation

Do not enable a broad MCP bundle by default. MCP is valuable when it connects Cursor to a specific reviewed system, but MCP tools can query databases, call APIs, modify files, or trigger other logic. The MCP spec explicitly treats tools as model-invoked capabilities and recommends visible tools, invocation indicators, and human confirmation for operations.

Use this priority order:

1. Cursor rules and local scripts first.
2. Read-only or low-risk MCP servers second.
3. Write-capable MCP servers only after the exact workflow and permissions are reviewed.

## Useful MCP Candidates

| Candidate | Use here | Permission stance |
| --- | --- | --- |
| GitHub | Read PRs, issues, CI failures, review comments, and release context. Useful once PR flow grows. | Start read-only. Allow write only for branch/PR automation when requested. |
| Playwright | Inspect the local web cabinet in Cursor, screenshots, basic UI flows. | Localhost only. No production credentials. |
| Sentry | Read recent beta errors if Sentry is configured. | Read-only token. No issue mutation by default. |
| Postgres or DuckDB | Query sanitized dev data, analytics, audit summaries, schema exploration. | Read-only dev DB or sanitized export only. Never production write access. |
| Notion or Linear | Pull roadmap/spec/task context if the project starts using those tools. | Read-only until task workflow is stable. |
| Filesystem | Usually unnecessary because Cursor already sees the workspace. | Avoid broad access. If used, root-bound and exclude secrets/artifacts. |

## Not Recommended Yet

- Active `.cursor/mcp.json` committed with real tokens or private IDs.
- Unreviewed marketplace MCP servers with local shell, filesystem, or database access.
- Production database MCP with write permissions.
- Email, Slack, calendar, or browser MCP for this repo unless there is a concrete project workflow.
- Any MCP path that reads `.env`, raw uploads, backups, local database files, or generated audit artifacts.

## Safe Project MCP Policy

If an active `.cursor/mcp.json` is added later:

- Keep secrets out of git. Use `${env:NAME}` interpolation only.
- Prefer project config for non-secret command shape and global/user config for personal tokens.
- Pin server packages or use reviewed local paths where practical.
- Keep write tools behind manual approval.
- Document every server in this file: purpose, permissions, token source, and how to disable it.
- Test with a harmless read-only request before using it in an agent run.

Template shape only:

```json
{
  "mcpServers": {
    "reviewed-local-server": {
      "command": "node",
      "args": ["C:/absolute/path/to/reviewed/server.js"],
      "env": {
        "EXAMPLE_TOKEN": "${env:EXAMPLE_TOKEN}"
      }
    }
  }
}
```

Do not copy this template into `.cursor/mcp.json` until the server package, scopes, and secret handling are reviewed.

## References

- Cursor Rules: https://docs.cursor.com/context/rules
- Cursor MCP: https://docs.cursor.com/advanced/model-context-protocol
- Cursor MCP servers catalog: https://docs.cursor.com/en/tools/mcp
- MCP server concepts: https://modelcontextprotocol.io/docs/learn/server-concepts
- MCP tools specification: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
