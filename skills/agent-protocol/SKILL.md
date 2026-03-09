---
name: agent-protocol
description: Required protocol for all agents — status reporting, Gitea API, transactions, and tooling conventions
---

# Agent Protocol

**This is mandatory for all agents.** Hooks will verify compliance.

## 1. Status Reporting

Every agent MUST report status. The dashboard and future visual HQ depend on this.

### On Session Start
```bash
source ~/.claude/lib/agent-status.sh
export CLAUDE_AGENT_NAME="your-agent-name"  # e.g., "pm", "dev-lead-ms", "pixel"
agent_status_update "idle" "Ready"
```

### When Starting Work
```bash
agent_status_update "working" "Description of current task" "tquick/repo-name" 42
```

### States
| State | When | Visual (future HQ) |
|-------|------|---------------------|
| `idle` | No active task | Agent in lounge |
| `working` | Actively on a task | Agent at desk, typing |
| `reviewing` | Reviewing code/PR | Agent at review station |
| `brainstorming` | Design/brainstorm session | Agent at whiteboard |
| `meeting` | Meeting scribe is live | Agent in meeting room |
| `blocked` | Waiting on dependency/human | Agent pacing |
| `starting` | Session initializing | Agent walking in |
| `stopping` | Session ending | Agent walking out |

### On Task Change
Call `agent_status_update` again with new state/task. Heartbeat is automatic via hooks.

### On Session End
```bash
agent_status_clear
```

## 2. Gitea API Access

**NEVER use raw curl to Gitea.** Always use the shared library.

### Setup
```bash
source ~/.claude/lib/gitea-api.sh
```

### Available Functions
```bash
# GET request
gitea_get "repos/tquick/meeting-scribe/issues" "state=open&limit=10"

# POST request (simple JSON)
gitea_post "repos/tquick/meeting-scribe/issues/1/comments" '{"body":"Comment text"}'

# PATCH request
gitea_patch "repos/tquick/meeting-scribe/issues/1" '{"state":"closed"}'

# Create issue (handles complex bodies safely)
gitea_create_issue "tquick/meeting-scribe" "Issue title" "Issue body" "1,2,3"
```

### Why Not Raw Curl?
- Gitea is behind Caddy basic auth — the library handles dual-auth automatically
- The API URL (`git.wastelandwares.com`) may change — library reads from env
- Token management is centralized — update one place, all agents get it
- Shell escaping for JSON bodies is error-prone — library uses temp files

### Deprecated
- `localhost:3003` — **BLOCKED BY HOOK**. Use `git.wastelandwares.com`.
- `project-management.wastelandwares.com` — Being repurposed for pipeline monitoring.

## 3. Worktree Isolation (Dev Agents)

All dev work MUST happen in worktrees:

```bash
# Create worktree for a story
git worktree add ../.worktrees/issue-17-assistant-skeleton -b feat/issue-17-assistant-skeleton

# Work in the worktree
cd ../.worktrees/issue-17-assistant-skeleton

# Clean up after merge
git worktree remove ../.worktrees/issue-17-assistant-skeleton
```

**Hook enforces**: Dev agents get warnings if they `cd` into the main working tree.

## 4. Transactions — Grouping Work with Intent

Every meaningful unit of work should be wrapped in a transaction.

### Setup
```bash
source ~/.claude/lib/agent-tx.sh
```

### Usage
```bash
# Start a transaction — state your intent and justify it
tx_begin "Implementing rolling summary" "Sprint 1 story #18" "tquick/meeting-scribe" 18

# Log each significant action with what + why
tx_action "Created src/summary_prompt.py" "Prompt template for condensed meeting minutes"
tx_action "Updated pipeline.py" "Integrated summary into batch loop"

# End the transaction with outcome
tx_end "success" "Rolling summary working, broadcasts every 2 minutes"
```

### Outcomes
- `success` — completed as intended
- `partial` — some goals met, others deferred
- `failed` — couldn't complete, needs retry or redesign
- `cancelled` — abandoned intentionally

### What Makes a Good Transaction
- **Intent**: Human-readable, high-level ("Implementing rolling summary" not "editing files")
- **Justification**: Why this is being done now ("Sprint 1 story #18")
- **Actions**: Describe what changed and why, not tool-level details
  - Good: `tx_action "Added Ollama health check" "Startup should fail gracefully if Ollama is down"`
  - Bad: `tx_action "Edited main.py line 42" "Changed code"`

## 5. Persona File Updates

Every agent MUST update their persona file (`~/.claude/agents/CLAUDE.{name}.md`) with learnings after each session.

## 6. Commit Conventions

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation
- `infra:` infrastructure/tooling
- `refactor:` restructuring
- `test:` test changes
- `chore:` maintenance

## Quick Reference

```bash
# At session start:
source ~/.claude/lib/agent-status.sh
source ~/.claude/lib/gitea-api.sh
source ~/.claude/lib/agent-tx.sh
export CLAUDE_AGENT_NAME="my-name"
agent_status_update "idle" "Ready"

# Begin focused work:
tx_begin "What I'm doing" "Why I'm doing it" "tquick/repo" 42
tx_action "What changed" "Why it changed"
tx_end "success" "Brief summary of outcome"

# Gitea operations:
issues=$(gitea_get "repos/tquick/meeting-scribe/issues" "state=open")
gitea_post "repos/tquick/meeting-scribe/issues/1/comments" '{"body":"Done!"}'

# At session end:
agent_status_clear
```
