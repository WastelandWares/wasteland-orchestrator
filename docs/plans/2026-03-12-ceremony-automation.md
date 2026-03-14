# Agent Ceremony Automation

**Date**: 2026-03-12
**Issues**: #48, #53, #54, #55
**Status**: Implemented

## Problem

Agents waste 10-15 turns on startup ceremony:
- Manually sourcing libraries (`source ~/.claude/lib/agent-status.sh`)
- Reading pinboard (`~/.claude/bin/pinboard read`)
- Setting agent name (`export CLAUDE_AGENT_NAME=...`)
- Starting transactions (`tx_begin ...`)
- Checking project status

This is overhead that should be automated via Claude Code hooks.

## Solution

### Issue #53 — Pinboard Read in SessionStart Hook

**File**: `~/.claude/hooks/agent-startup.sh`

The SessionStart hook now reads `~/.claude/pinboard.json` and injects active
pins into the agent's context via `hookSpecificOutput.additionalContext`.

Agents no longer need to run `~/.claude/bin/pinboard read` — pins appear
automatically in a `<pinboard>` tag in their context.

### Issue #54 — Auto tx_begin on Subagent Spawn

**Files**: `~/.claude/hooks/subagent-start.sh`, `~/.claude/hooks/subagent-stop.sh`

New `SubagentStart` and `SubagentStop` hooks registered in `~/.claude/settings.json`:

- **SubagentStart**: Fires `tx_begin` automatically for real subagents (skips
  built-in lightweight agents like Bash, Explore, Plan). Injects context about
  the parent agent and dispatch instructions.
- **SubagentStop**: Fires `tx_end` automatically, closing the transaction
  with a success outcome.

Agents no longer need to manually call `tx_begin`/`tx_end`.

### Issue #55 — Pass PM Context to Dev-Leads

**Files**: `~/.claude/state/dispatch-context.json` (runtime), `~/.claude/lib/dispatch.sh`

New dispatch context system:

1. PM (or any dispatcher) calls `dispatch_write_context` before spawning an agent
2. Writes a JSON file at `~/.claude/state/dispatch-context.json` containing:
   - Briefing summary
   - Issue bodies (fetched from Gitea)
   - Recent commits
   - Cross-project dependencies
   - Custom instructions
3. SessionStart hook reads this file and injects it as `<dispatch-context>`
4. File is marked as consumed after injection (with TTL check: 5 min)

The `agent-spawn` wrapper also writes this context automatically.

### Issue #48 — Enforce Agent Metadata via Spawn Tooling

**Files**: `~/.claude/bin/agent-spawn`, `~/.claude/hooks/agent-startup.sh`

Two-pronged approach:

1. **`agent-spawn` wrapper**: Sets `CLAUDE_AGENT_NAME`, creates the status file,
   and writes dispatch context BEFORE the Claude session starts. Usage:
   ```bash
   agent-spawn --agent=dev-lead --project=dnd-tools --issue=8
   ```

2. **SessionStart hook + CLAUDE_ENV_FILE**: The hook detects the agent name from:
   - `CLAUDE_AGENT_NAME` env var (set by spawn wrapper)
   - `agent_type` from hook input (set by `--agent` flag)
   - Dispatch context file
   - Directory-based inference (fallback)

   It then writes `export CLAUDE_AGENT_NAME="..."` to `$CLAUDE_ENV_FILE`,
   which Claude Code makes available to all subsequent Bash tool calls.

## Settings Changes

`~/.claude/settings.json` now includes:

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "agent-startup.sh", "timeout": 15 }] }],
    "SubagentStart": [{ "hooks": [{ "type": "command", "command": "subagent-start.sh", "timeout": 10 }] }],
    "SubagentStop": [{ "hooks": [{ "type": "command", "command": "subagent-stop.sh", "timeout": 10 }] }],
    "PreToolUse": [{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "verify-agent-protocol.sh" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "agent-shutdown.sh" }] }]
  }
}
```

## Dispatch Context Schema

```json
{
  "agent_name": "dev-lead",
  "repo": "tquick/dnd-tools",
  "issue_number": "8",
  "created_at": "2026-03-12T14:00:00+00:00",
  "created_by": "pm",
  "consumed": false,
  "briefing_summary": "...",
  "issue_bodies": [{ "number": 8, "title": "...", "body": "...", "labels": [] }],
  "recent_commits": "abc123 feat: ...\ndef456 fix: ...",
  "cross_dependencies": "...",
  "phase_plan": "...",
  "custom_instructions": "..."
}
```

## Turn Savings

Before: ~10-15 turns of ceremony per agent session
After: 0 turns — everything happens in hooks before the agent's first response

| Action | Before | After |
|--------|--------|-------|
| Source libraries | 1-2 turns | Hook (auto) |
| Set agent name | 1 turn | Hook + CLAUDE_ENV_FILE (auto) |
| Read pinboard | 1-2 turns | Hook → additionalContext (auto) |
| tx_begin | 1 turn | SubagentStart hook (auto) |
| Read dispatch context | 2-3 turns | Hook → additionalContext (auto) |
| Create status file | 1 turn | Hook + spawn wrapper (auto) |
| **Total** | **~10 turns** | **0 turns** |
