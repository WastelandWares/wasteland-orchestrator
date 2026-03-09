---
name: tx
description: Manage transactions — begin, log actions, end, or view history
---

# /tx — Transaction Management

Manage work transactions for audit trail and dashboard visibility.

## Subcommands

### `/tx begin <intent> | <justification>`
Start a new transaction:
```bash
source ~/.claude/lib/agent-tx.sh
tx_begin "Implementing feature X" "Sprint 1 story #42" "tquick/repo" 42
```

### `/tx action <what> | <why>`
Log an action in the current transaction:
```bash
tx_action "Created src/feature.py" "Core implementation of feature X"
```

### `/tx end <outcome> [summary]`
End the current transaction:
```bash
tx_end "success" "Feature X implemented and tested"
```
Outcomes: `success`, `partial`, `failed`, `cancelled`

### `/tx current`
Show the active transaction for this agent.

### `/tx recent [count]`
Show the most recent transactions across all agents (default: 10).

## Notes
- Transactions are archived to `~/.claude/agents/transactions/log/`
- If a session ends with an active transaction, the stop hook marks it as `interrupted`
- The dashboard reads active transactions for real-time visibility
