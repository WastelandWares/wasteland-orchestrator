# Wasteland Orchestrator

A Claude Code plugin for multi-agent orchestration: status reporting, transactions, team coordination, and real-time dashboard for AI agent workflows.

## What It Does

- **Agent Status Tracking** — Every agent reports what it's doing in real-time via structured status files
- **Ceremony Automation** — Hooks automatically orchestrate agent initialization (spawn setup, heartbeat, status registration)
- **Transaction System** — Groups related actions into auditable units with stated intent and justification
- **Gitea API Library** — Centralized, dual-auth Gitea access (handles Caddy basic auth + Gitea tokens)
- **Protocol Enforcement** — PreToolUse hooks verify agents follow conventions (no raw curl, worktree isolation, etc.)
- **Dashboard Ready** — Status files and transaction logs feed terminal dashboards and future visual HQ

## Installation

### As a Claude Code Plugin
```bash
# From the Claude Code CLI
claude plugin add wasteland-orchestrator
```

### Manual
```bash
git clone https://git.wastelandwares.com/tquick/wasteland-orchestrator.git
# Add to your Claude Code project's plugin configuration
```

## Structure

```
wasteland-orchestrator/
  .claude-plugin/
    plugin.json          # Plugin manifest
  hooks/
    hooks.json           # Hook registration
    pretooluse.py        # PreToolUse: heartbeat, Gitea enforcement, worktree checks
    posttooluse.py       # PostToolUse: heartbeat, tool tracking
    stop.py              # Stop: cleanup status, archive interrupted transactions
  lib/
    agent_status.sh      # Agent status reporting (shell wrapper)
    agent_status.py      # Agent status reporting (Python)
    agent_tx.sh          # Transaction system (shell wrapper)
    agent_tx.py          # Transaction system (Python)
    gitea_api.sh         # Gitea API client (shell wrapper)
    gitea_api.py         # Gitea API client (Python)
  tools/
    ww-json-tool.py      # JSON processing utility for agent workflows
  skills/
    agent-protocol/
      SKILL.md           # Mandatory protocol documentation
  commands/
    status.md            # /status slash command
    tx.md                # /tx slash command
  docs/
    VOCABULARY.md        # Agent protocol terminology guide
    ARCHITECTURE.md      # System design and data flow diagrams
```

## Protocol Overview

All agents must:
1. Report status via `agent_status_update` (hooks handle heartbeat automatically)
2. Use shared Gitea API library (hooks warn on raw curl, block deprecated endpoints)
3. Wrap work in transactions with intent/justification
4. Work in git worktrees (dev agents only, enforced by hooks)
5. Update persona files with learnings after each session

See `skills/agent-protocol/SKILL.md` for the full protocol specification.

## Documentation

- **VOCABULARY.md** — Terminology guide for agent roles, states, and workflow concepts
- **ARCHITECTURE.md** — Visual system design including agent initialization flow and transaction lifecycle
- **Ceremony Automation** — Hooks automatically initialize agents with proper status tracking and spawn handling

## Agent States

| State | Meaning |
|-------|---------|
| idle | No active task |
| working | Actively on a task |
| reviewing | Reviewing code/PR |
| brainstorming | Design session |
| meeting | Meeting scribe live |
| blocked | Waiting on dependency |

## Transaction Example

```python
from lib.agent_tx import Transaction

tx = Transaction("dev-lead-ms")
tx.begin("Implementing assistant skeleton", "Phase 1 task #17", repo="tquick/meeting-scribe", issue=17)
tx.action("Created src/assistant.py", "Core assistant class with Ollama client")
tx.action("Updated pipeline.py", "Integrated assistant as post-transcription stage")
tx.end("success", "Assistant skeleton in place, ready for model integration")
```

## License

MIT
