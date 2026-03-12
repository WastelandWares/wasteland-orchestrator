---
name: status
description: Show current agent statuses and active transactions
---

# /status — Agent Status Dashboard

Show what all agents are doing right now.

## Behavior

When the user runs `/status`, do the following:

1. Read all status files from `~/.claude/agents/status/*.json`
2. Read all active transactions from `~/.claude/agents/transactions/*.current.json`
3. Present a clean summary:

```
## Agent Status
| Agent | State | Task | Last Heartbeat | Alive |
|-------|-------|------|----------------|-------|
| pm | working | Planning phase 2 | 30s ago | yes |
| dev-lead-ms | idle | Ready | 2m ago | yes |

## Active Transactions
| Agent | Intent | Actions | Started |
|-------|--------|---------|---------|
| pm | Planning phase 2 | 3 actions | 5m ago |
```

4. Flag any stale agents (heartbeat > 5 minutes) or dead processes
5. If no agents are active, say so clearly

## Implementation

Use the Python libraries:
```python
from lib.agent_status import list_agents
from lib.agent_tx import Transaction
```

Or read the JSON files directly from the filesystem.
