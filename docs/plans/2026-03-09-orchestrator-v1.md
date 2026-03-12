# Wasteland Orchestrator v1.0 — Phase Plan

> **Priority**: This is THE priority. Orchestrator v1 unblocks everything else.
> **Approved**: 2026-03-09
> **Issues**: #1, #2, #3, #4, #5, #6

---

## What We Have (v0.1.0)

| Component | Status | Notes |
|-----------|--------|-------|
| Agent status files | **Working** | JSON at ~/.claude/agents/status/*.json |
| Status Python lib | **Working** | `AgentStatus` class, `list_agents()` |
| Transaction system | **Working** | `Transaction` class, begin/action/end, log archive |
| Gitea API client | **Working** | `GiteaClient` with dual-auth, CRUD for issues |
| PreToolUse hook | **Working** | Heartbeat, Gitea enforcement, worktree warnings |
| Stop hook | **Working** | Status cleanup, interrupted tx archival |
| Bash shell libs | **Working** | agent-status.sh, gitea-api.sh, agent-tx.sh |
| Slash commands | **Working** | /status, /tx |

## What We Need (v1.0)

| Component | Issue | Complexity |
|-----------|-------|-----------|
| Phase manifest format | #1 | small |
| Dispatcher (the brain) | #2 | large |
| Health monitor | #3 | medium |
| Conflict detection | #4 | medium |
| Gitea auto-updates | #5 | small |
| PM manifest generator | #6 | small |

---

## Implementation Order

### Phase 1: Foundation (do first, enables everything)

**#1 Phase Manifest** → Define the YAML format. Everything reads from this.

**#6 PM Manifest Generator** → So we can auto-produce manifests from Gitea issues.

### Phase 2: Core Dispatcher (the main build)

**#2 Dispatcher** → The main `swarm.py` that:
- Parses manifest
- Builds dependency DAG
- Spawns `claude -p` agents with correct context
- Tracks PIDs and maps to tasks
- Waits for completion

### Phase 3: Safety & Polish

**#4 Conflict Detection** → File ownership graph, serialization of overlapping tasks.

**#3 Health Monitor** → Heartbeat checks, stall detection, retry logic.

**#5 Gitea Integration** → Auto-close issues, progress comments.

---

## Architecture

```
                    ┌─────────────────────┐
                    │   PM Agent (Elara)  │
                    │  Designs phase,    │
                    │  generates manifest │
                    └─────────┬───────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │    phase.yaml      │
                    │  (manifest file)    │
                    └─────────┬───────────┘
                              │
                              ▼
            ┌─────────────────────────────────┐
            │        swarm.py (dispatcher)     │
            │                                  │
            │  ┌──────────┐  ┌──────────────┐ │
            │  │ DAG /    │  │  Conflict    │ │
            │  │ Scheduler│  │  Detector    │ │
            │  └────┬─────┘  └──────────────┘ │
            │       │                          │
            │  ┌────┴─────────────────────┐   │
            │  │     Agent Monitor        │   │
            │  │  heartbeat / stall /     │   │
            │  │  retry / Gitea updates   │   │
            │  └──┬──────┬──────┬─────────┘   │
            └─────┼──────┼──────┼─────────────┘
                  │      │      │
          ┌───────┘      │      └───────┐
          ▼              ▼              ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ claude -p│  │ claude -p│  │ claude -p│
    │ dev-ui   │  │ dev-intg │  │ dev-test │
    │ task #8 │  │ task #16│  │ task #17│
    └──────────┘  └──────────┘  └──────────┘
          │              │              │
          ▼              ▼              ▼
    status/*.json  status/*.json  status/*.json
```

## Key Design Decisions

1. **`claude -p` not interactive sessions**: Print mode exits when done, gives us clean process lifecycle. Budget caps work. Output is capturable.

2. **YAML manifest not database**: Human-editable, version-controllable, reviewable before dispatch. PM can tweak before launching.

3. **File-based monitoring not IPC**: Status JSON files are the communication channel. No sockets, no message queues. Simple, debuggable, already working.

4. **Serialization over conflict resolution**: v1 prevents conflicts by never running overlapping tasks in parallel. Smarter merging can come in v2.

5. **One worktree per phase, not per task**: Keeps git simple. Tasks run sequentially when they share files, so the single worktree stays clean.

---

## Success Criteria

After v1.0, running a phase looks like:

```bash
# PM generates manifest from Gitea issues
python3 generate_manifest.py tquick/claude-gate --output phase.yaml

# Human reviews/tweaks manifest
vim phase.yaml

# Launch the swarm
python3 swarm.py phase.yaml

# Watch progress (separate terminal)
python3 swarm.py --status

# Or just watch Gitea — issues auto-close as tasks complete
```

No manual `claude -p` commands. No copy-pasting prompts. No checking terminals.
The dispatcher handles spawn, monitor, retry, report, close.
