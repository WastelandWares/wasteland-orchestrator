# Cook Mode — "Let Claude Cook" 🔥

## Overview

Cook mode enables autonomous work sessions where Claude works continuously without interruption. User messages are queued via the btw system and processed at task boundaries.

## Commands

- **`/cook [task description]`** — Activate cook mode with an optional task description
- **`/uncook`** — Deactivate cook mode and show queued message summary
- **Exit keywords**: "stop", "pause", "hey", "hey claude", "hold on", "wait", "halt"

## Architecture

### Files

| File | Purpose |
|------|---------|
| `~/.claude/lib/cook.sh` | Shell helpers (activate, deactivate, queue, check exit) |
| `~/.claude/commands/cook.md` | `/cook` slash command definition |
| `~/.claude/commands/uncook.md` | `/uncook` slash command definition |
| `~/.claude/state/cook-mode.json` | Persistent state file |

### State File Schema

```json
{
  "active": true,
  "started_at": "2026-03-11T10:30:00",
  "task": "Implementing auth system",
  "messages_queued": 3,
  "exit_keywords": ["stop", "pause", "hey", "hey claude", "hold on", "wait", "halt"]
}
```

### Integration Points

- **Statusline**: Shows `🔥 COOKING` prefix when active
- **HQ Dashboard**: Displays cook mode badge with task and queue count
- **btw queue**: Queued messages are tagged with `cook_mode: true`
- **hq-status-writer.py**: Exposes `cook_mode` field in status.json

## Behavioral Contract

When cook mode is active:

1. **User messages are queued**, not processed inline
2. **Brief acknowledgment** is given: `📝 Queued: "<summary>"`
3. **Exit keywords** checked before queuing — if detected, cook mode deactivates
4. **Task boundaries** are natural checkpoints to review the queue
5. **State persists** across context compactions (stored on filesystem)

## Shell Library API

```bash
source ~/.claude/lib/cook.sh

cook_is_active              # Returns 0 if active, 1 if not
cook_activate "my task"     # Activates cook mode
cook_deactivate             # Deactivates and shows summary
cook_queue_message "text"   # Queues a message with cook_mode tag
cook_check_exit "stop"      # Prints "exit" or "continue"
```

## Installation

The cook.sh library and command files are installed from wasteland-orchestrator:

```bash
# From the repo:
cp lib/cook.sh ~/.claude/lib/cook.sh
cp commands/cook.md ~/.claude/commands/cook.md
cp commands/uncook.md ~/.claude/commands/uncook.md
mkdir -p ~/.claude/state
```
